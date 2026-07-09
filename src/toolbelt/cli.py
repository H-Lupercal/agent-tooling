from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError as PydanticValidationError

from toolbelt import __version__
from toolbelt.adapters.base import run_inventory_command
from toolbelt.adapters.claude import ClaudeAdapter
from toolbelt.adapters.codex import CodexAdapter
from toolbelt.capabilities import combine_capabilities
from toolbelt.catalog import CatalogV2, load_catalog_v2
from toolbelt.doctor import doctor_report, status_report
from toolbelt.errors import (
    DeclinedError,
    InternalError,
    ToolbeltError,
    UsageError,
    ValidationError,
)
from toolbelt.executor import ExecutionResult, Executor
from toolbelt.migration import migrate_v1_candidate
from toolbelt.paths import resolve_owned_path
from toolbelt.planner import (
    build_explicit_plan_v2,
    build_plan_v2,
    read_plan_v2,
    write_plan_v2,
)
from toolbelt.policy import Recommendation, recommend
from toolbelt.rendering import emit_json, error_response, response
from toolbelt.scanner import ScanResult, scan_repository
from toolbelt.schemas import (
    ActionOperation,
    ActionV2,
    CapabilitySnapshot,
    CatalogToolV2,
)
from toolbelt.state import load_declaration


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    data: dict[str, Any]
    human: str
    exit_code: int = 0


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="toolbelt", description="Deterministic AI developer-tool management")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--debug", action="store_true", help="show tracebacks for internal errors")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="scan repository evidence without writing state")
    _project_arguments(scan)
    _output_arguments(scan)

    discover = commands.add_parser("discover", help="show conservative recommendations")
    _project_arguments(discover)
    _capability_arguments(discover)
    _output_arguments(discover)

    plan = commands.add_parser("plan", help="create a digest-bound v2 plan")
    _project_arguments(plan)
    _capability_arguments(plan)
    _approval_arguments(plan, mutation=False)
    plan.add_argument("--out", help="repository-relative output path")
    _output_arguments(plan)

    apply = commands.add_parser("apply", help="transactionally execute a v2 plan")
    _project_arguments(apply)
    _capability_arguments(apply)
    _approval_arguments(apply, mutation=True)
    apply.add_argument("--plan", required=True, help="plan JSON path")
    apply.add_argument("--dry-run", action="store_true", help="preflight without commands")
    _output_arguments(apply)

    status = commands.add_parser("status", help="inspect declaration and local state")
    _project_arguments(status)
    _output_arguments(status)

    doctor = commands.add_parser("doctor", help="run distribution or project readiness checks")
    doctor.add_argument("--path", help="optional project path; omit for distribution-only checks")
    doctor.add_argument("--capabilities", help="strict capability snapshot JSON")
    doctor.add_argument("--strict", action="store_true", help="treat warnings as not ready")
    _output_arguments(doctor)

    verify = commands.add_parser("verify", help="run declared tool verification contracts")
    _project_arguments(verify)
    _capability_arguments(verify)
    _approval_arguments(verify, mutation=False)
    verify.add_argument("--tool", help="verify one declared tool")
    _output_arguments(verify)

    adopt = commands.add_parser("adopt", help="verify and declare an existing unmanaged tool")
    adopt.add_argument("tool")
    _project_arguments(adopt)
    _capability_arguments(adopt)
    _approval_arguments(adopt, mutation=True)
    _output_arguments(adopt)

    remove = commands.add_parser("remove", help="transactionally remove a declared tool")
    remove.add_argument("tool")
    _project_arguments(remove)
    _capability_arguments(remove)
    _approval_arguments(remove, mutation=True)
    _output_arguments(remove)

    reconcile = commands.add_parser("reconcile", help="report catalog, declaration, and inventory drift")
    _project_arguments(reconcile)
    _capability_arguments(reconcile)
    _output_arguments(reconcile)

    recover = commands.add_parser("recover", help="resume rollback for an interrupted transaction")
    recover.add_argument("transaction_id")
    _project_arguments(recover)
    recover.add_argument("--yes", action="store_true", help="approve recovery mutation")
    _output_arguments(recover)

    catalog = commands.add_parser("catalog", help="catalog operations")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    validate = catalog_commands.add_parser("validate", help="validate a strict v2 catalog")
    validate.add_argument("path", nargs="?", help="catalog path; omit for bundled catalog")
    _output_arguments(validate)

    migrate = commands.add_parser("migrate-v1", help="write a disabled v2 migration candidate")
    _project_arguments(migrate)
    migrate.add_argument("--out", required=True, help="repository-relative candidate path")
    _output_arguments(migrate)
    return parser


def _project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--path", default=".", help="repository root")


def _capability_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--capabilities", help="strict capability snapshot JSON")


def _approval_arguments(parser: argparse.ArgumentParser, *, mutation: bool) -> None:
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-user-scope", action="store_true")
    parser.add_argument("--allow-elevation", action="store_true")
    if mutation:
        parser.add_argument("--yes", action="store_true", help="approve the requested mutation")


def _output_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="emit one stable JSON object")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    wants_json = "--json" in arguments
    command = _requested_command(arguments)
    debug = "--debug" in arguments
    try:
        parsed = build_parser().parse_args(arguments)
        command = parsed.command if parsed.command != "catalog" else f"catalog {parsed.catalog_command}"
        outcome = _dispatch(parsed)
        if parsed.json:
            emit_json(response(command, outcome.data))
        elif outcome.human:
            print(outcome.human)
        return outcome.exit_code
    except ToolbeltError as exc:
        return _render_error(command, exc, wants_json=wants_json, debug=debug)
    except (PydanticValidationError, ValueError) as exc:
        error = ValidationError(str(exc))
        return _render_error(command, error, wants_json=wants_json, debug=debug)
    except Exception as exc:  # defensive CLI boundary
        error = InternalError("unexpected internal failure")
        if debug:
            traceback.print_exc(file=sys.stderr)
        else:
            print(f"internal error: {type(exc).__name__}", file=sys.stderr)
        return _render_error(command, error, wants_json=wants_json, debug=debug)


def _dispatch(args: argparse.Namespace) -> CommandOutcome:
    handlers: dict[str, Callable[[argparse.Namespace], CommandOutcome]] = {
        "scan": _scan,
        "discover": _discover,
        "plan": _plan,
        "apply": _apply,
        "status": _status,
        "doctor": _doctor,
        "verify": _verify,
        "adopt": _adopt,
        "remove": _remove,
        "reconcile": _reconcile,
        "recover": _recover,
        "catalog": _catalog,
        "migrate-v1": _migrate,
    }
    return handlers[args.command](args)


def _scan(args: argparse.Namespace) -> CommandOutcome:
    root = _root(args.path)
    result = scan_repository(root)
    data = _scan_data(result)
    human = "\n".join(
        f"{item.strength.value:8} {item.type}:{item.key} ({item.source})"
        for item in result.evidence
    ) or "No repository evidence found."
    return CommandOutcome(data, human)


def _discover(args: argparse.Namespace) -> CommandOutcome:
    root = _root(args.path)
    catalog = load_catalog_v2()
    scan = scan_repository(root)
    capabilities = _load_capabilities(args.capabilities)
    recommendations = recommend(catalog, scan.evidence, capabilities)
    data = {
        **_scan_data(scan),
        "capabilities": capabilities.model_dump(mode="json"),
        "recommendations": [_recommendation_data(item) for item in recommendations],
    }
    human = "\n".join(
        f"{'ACTION' if item.actionable else 'ADVISORY':8} {item.tool_id}: {item.why}"
        for item in recommendations
    ) or "No recommendations."
    return CommandOutcome(data, human)


def _plan(args: argparse.Namespace) -> CommandOutcome:
    root = _root(args.path)
    catalog = load_catalog_v2()
    scan = scan_repository(root)
    capabilities = _load_capabilities(args.capabilities)
    plan = build_plan_v2(
        root,
        scan.evidence,
        catalog,
        capabilities,
        allow_network=args.allow_network,
        allow_user_scope=args.allow_user_scope,
    )
    output = None
    if args.out:
        output_path = Path(args.out)
        if output_path.is_absolute():
            try:
                output_path = output_path.resolve().relative_to(root)
            except ValueError as exc:
                raise ValidationError("plan output must remain inside the repository") from exc
        target = resolve_owned_path(root, output_path.as_posix())
        write_plan_v2(plan, target)
        output = str(target)
    data = {
        "plan": plan.model_dump(mode="json"),
        "output": output,
        "warnings": [asdict(warning) for warning in scan.warnings],
    }
    return CommandOutcome(data, f"Plan {plan.plan_id}: {len(plan.actions)} action(s)" + (f" -> {output}" if output else ""))


def _apply(args: argparse.Namespace) -> CommandOutcome:
    if not args.dry_run and not args.yes:
        raise DeclinedError("apply requires --yes unless --dry-run is used")
    root = _root(args.path)
    catalog = load_catalog_v2()
    capabilities = _load_capabilities(args.capabilities)
    plan = read_plan_v2(args.plan)
    result = Executor().apply(
        plan,
        root,
        catalog,
        capabilities,
        allow_network=args.allow_network,
        allow_user_scope=args.allow_user_scope,
        allow_elevation=args.allow_elevation,
        dry_run=args.dry_run,
    )
    return _execution_outcome(result)


def _status(args: argparse.Namespace) -> CommandOutcome:
    report = status_report(_root(args.path))
    incomplete = report["state"]["incomplete_transactions"]
    human = (
        f"Declared tools: {len((report['declaration'] or {}).get('tools', []))}\n"
        f"Transactions: {report['state']['transaction_count']}\n"
        f"Incomplete: {len(incomplete)}"
    )
    return CommandOutcome(report, human, exit_code=1 if incomplete else 0)


def _doctor(args: argparse.Namespace) -> CommandOutcome:
    capabilities = None
    root = None
    if args.path is not None:
        root = _root(args.path)
        capabilities = _load_capabilities(args.capabilities)
    report = doctor_report(root=root, capabilities=capabilities, strict=args.strict)
    human = "\n".join(
        f"{'PASS' if check['ok'] else check['severity'].upper()}: {check['code']} - {check['message']}"
        for check in report["checks"]
    )
    return CommandOutcome(report, human, exit_code=0 if report["ready"] else 1)


def _verify(args: argparse.Namespace) -> CommandOutcome:
    root = _root(args.path)
    declaration = _required_declaration(root)
    catalog = load_catalog_v2()
    capabilities = _load_capabilities(args.capabilities)
    catalog_by_id = {tool.id: tool for tool in catalog}
    selected = [tool for tool in declaration.tools if args.tool is None or tool.tool_id == args.tool]
    if args.tool and not selected:
        raise ValidationError(f"tool is not declared: {args.tool}")
    actions = [
        _explicit_action(catalog_by_id[declared.tool_id], ActionOperation.VERIFY, index)
        for index, declared in enumerate(selected, start=1)
        if declared.tool_id in catalog_by_id
    ]
    if len(actions) != len(selected):
        raise ValidationError("one or more declared tools no longer exist in the catalog")
    plan = build_explicit_plan_v2(root, catalog, capabilities, actions)
    result = Executor().apply(
        plan,
        root,
        catalog,
        capabilities,
        allow_network=args.allow_network,
        allow_user_scope=args.allow_user_scope,
        allow_elevation=args.allow_elevation,
    )
    return _execution_outcome(result)


def _adopt(args: argparse.Namespace) -> CommandOutcome:
    _require_yes(args)
    root = _root(args.path)
    catalog = load_catalog_v2()
    capabilities = _load_capabilities(args.capabilities)
    tool = _catalog_tool(catalog, args.tool)
    live_names = {tool.id, *(() if tool.live_name is None else (tool.live_name,))}
    if capabilities.status.value != "known" or not set(capabilities.installed).intersection(live_names):
        raise ValidationError("adoption requires known inventory proving the tool is installed")
    if set(capabilities.managed).intersection(live_names):
        raise ValidationError("tool is already managed")
    plan = build_explicit_plan_v2(
        root,
        catalog,
        capabilities,
        [_explicit_action(tool, ActionOperation.ADOPT, 1)],
    )
    result = Executor().apply(
        plan,
        root,
        catalog,
        capabilities,
        allow_network=args.allow_network,
        allow_user_scope=args.allow_user_scope,
        allow_elevation=args.allow_elevation,
    )
    return _execution_outcome(result)


def _remove(args: argparse.Namespace) -> CommandOutcome:
    _require_yes(args)
    root = _root(args.path)
    declaration = _required_declaration(root)
    if args.tool not in {tool.tool_id for tool in declaration.tools}:
        raise ValidationError(f"tool is not declared: {args.tool}")
    catalog = load_catalog_v2()
    capabilities = _load_capabilities(args.capabilities)
    tool = _catalog_tool(catalog, args.tool)
    plan = build_explicit_plan_v2(
        root,
        catalog,
        capabilities,
        [_explicit_action(tool, ActionOperation.REMOVE, 1)],
    )
    result = Executor().apply(
        plan,
        root,
        catalog,
        capabilities,
        allow_network=args.allow_network,
        allow_user_scope=args.allow_user_scope,
        allow_elevation=args.allow_elevation,
    )
    return _execution_outcome(result)


def _reconcile(args: argparse.Namespace) -> CommandOutcome:
    root = _root(args.path)
    declaration = load_declaration(root)
    catalog = load_catalog_v2()
    capabilities = _load_capabilities(args.capabilities)
    catalog_by_id = {tool.id: tool for tool in catalog}
    drift: list[dict[str, str]] = []
    for declared in () if declaration is None else declaration.tools:
        current = catalog_by_id.get(declared.tool_id)
        if current is None:
            drift.append({"tool_id": declared.tool_id, "kind": "orphaned_catalog_entry"})
        elif current.version != declared.version:
            drift.append({"tool_id": declared.tool_id, "kind": "version_drift"})
        live_names = {declared.tool_id}
        if current is not None and current.live_name is not None:
            live_names.add(current.live_name)
        if capabilities.status.value == "known" and not set(capabilities.installed).intersection(live_names):
            drift.append({"tool_id": declared.tool_id, "kind": "missing_live_tool"})
    data = {
        "drift": drift,
        "declaration_present": declaration is not None,
        "capability_status": capabilities.status.value,
    }
    human = "No drift detected." if not drift else "\n".join(f"{item['tool_id']}: {item['kind']}" for item in drift)
    return CommandOutcome(data, human, exit_code=1 if drift else 0)


def _recover(args: argparse.Namespace) -> CommandOutcome:
    _require_yes(args)
    result = Executor().recover(_root(args.path), args.transaction_id)
    return _execution_outcome(result)


def _catalog(args: argparse.Namespace) -> CommandOutcome:
    catalog = load_catalog_v2(None if args.path is None else Path(args.path))
    data = {
        "source": catalog.source,
        "digest": catalog.digest,
        "tool_count": len(catalog),
        "tools": [tool.id for tool in catalog],
    }
    return CommandOutcome(data, f"Valid v2 catalog: {len(catalog)} tool(s), digest {catalog.digest}")


def _migrate(args: argparse.Namespace) -> CommandOutcome:
    target, count = migrate_v1_candidate(_root(args.path), args.out)
    data = {"output": str(target), "candidate_count": count, "enabled": False}
    return CommandOutcome(data, f"Wrote {count} disabled candidate(s) to {target}")


def _explicit_action(
    tool: CatalogToolV2,
    operation: ActionOperation,
    index: int,
) -> ActionV2:
    if operation is ActionOperation.REMOVE:
        steps = (tool.rollback,)
        verify = ()
        rollback = (tool.install,)
    elif operation in {ActionOperation.ADOPT, ActionOperation.VERIFY}:
        steps = ()
        verify = (tool.verify,)
        rollback = ()
    else:
        raise ValidationError(f"unsupported explicit operation: {operation.value}")
    return ActionV2(
        id=f"a{index:04d}",
        operation=operation,
        tool_id=tool.id,
        tool_version=tool.version,
        install_scope=tool.install_scope,
        permissions=tool.permissions,
        confidence=1.0,
        why=f"Explicit {operation.value} request for {tool.name}",
        steps=steps,
        verify=verify,
        rollback=rollback,
        required_env=tool.required_env,
    )


def _execution_outcome(result: ExecutionResult) -> CommandOutcome:
    data = {
        "transaction_id": result.transaction_id,
        "state": result.state.value,
        "dry_run": result.dry_run,
        "error": result.error,
        "commands": [command.model_dump(mode="json") for command in result.commands],
    }
    exit_code = 0 if result.state.value == "succeeded" else (7 if result.state.value == "rollback_failed" else 6)
    return CommandOutcome(data, f"Transaction {result.transaction_id}: {result.state.value}", exit_code)


def _load_capabilities(path: str | None) -> CapabilitySnapshot:
    selected = path or os.environ.get("TOOLBELT_CAPABILITIES")
    if selected:
        source = Path(selected)
        try:
            if source.stat().st_size > 1024 * 1024:
                raise ValidationError("capability snapshot exceeds one MiB")
            raw = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValidationError("capability snapshot root must be an object")
            return CapabilitySnapshot.model_validate(raw)
        except FileNotFoundError as exc:
            raise ValidationError(f"capability snapshot not found: {source}") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(f"invalid capability snapshot: {exc}") from exc
    return combine_capabilities(
        (
            CodexAdapter().inventory(runner=run_inventory_command),
            ClaudeAdapter().inventory(runner=run_inventory_command),
        )
    )


def _scan_data(result: ScanResult) -> dict[str, Any]:
    return {
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "warnings": [asdict(item) for item in result.warnings],
        "files_scanned": result.files_scanned,
        "bytes_scanned": result.bytes_scanned,
    }


def _recommendation_data(item: Recommendation) -> dict[str, Any]:
    return {
        "tool_id": item.tool_id,
        "actionable": item.actionable,
        "why": item.why,
        "evidence": [evidence.model_dump(mode="json") for evidence in item.evidence],
        "missing_requirements": list(item.missing_requirements),
        "allowed_operations": list(item.allowed_operations),
        "confidence": item.confidence,
    }


def _required_declaration(root: Path):
    declaration = load_declaration(root)
    if declaration is None:
        raise ValidationError("no Toolbelt v2 declaration exists")
    return declaration


def _catalog_tool(catalog: CatalogV2, tool_id: str) -> CatalogToolV2:
    for tool in catalog:
        if tool.id == tool_id:
            return tool
    raise ValidationError(f"unknown catalog tool: {tool_id}")


def _root(value: str) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except OSError as exc:
        raise UsageError(f"project path does not exist: {value}") from exc
    if not root.is_dir():
        raise UsageError(f"project path is not a directory: {value}")
    return root


def _require_yes(args: argparse.Namespace) -> None:
    if not getattr(args, "yes", False):
        raise DeclinedError(f"{args.command} requires --yes")


def _requested_command(arguments: list[str]) -> str:
    for argument in arguments:
        if not argument.startswith("-"):
            return argument
    return "toolbelt"


def _render_error(
    command: str,
    error: ToolbeltError,
    *,
    wants_json: bool,
    debug: bool,
) -> int:
    code = _error_code(error)
    message = str(error) or code
    if wants_json:
        emit_json(
            error_response(
                command,
                code=code,
                message=message,
                exit_code=error.exit_code,
            )
        )
    else:
        print(f"{code}: {message}", file=sys.stderr)
    if debug and not isinstance(error, InternalError):
        traceback.print_exc(file=sys.stderr)
    return error.exit_code


def _error_code(error: ToolbeltError) -> str:
    name = type(error).__name__
    pieces: list[str] = []
    for character in name:
        if character.isupper() and pieces:
            pieces.append("_")
        pieces.append(character.upper())
    return "".join(pieces)


__all__ = ["build_parser", "main"]
