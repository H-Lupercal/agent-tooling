from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path, PurePosixPath

from toolbelt.catalog import CatalogV2
from toolbelt.errors import StalePlanError, ValidationError
from toolbelt.paths import repository_identity
from toolbelt.policy import recommend
from toolbelt.schemas import (
    ActionOperation,
    ActionV2,
    CapabilitySnapshot,
    EvidenceV2,
    PlanV2,
    RepositoryBinding,
)
from toolbelt.state import atomic_write_text

_MAX_BOUND_FILES = 25_000
_MAX_BOUND_BYTES = 64 * 1024 * 1024
_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)


def build_plan_v2(
    root: str | Path,
    evidence: list[EvidenceV2] | tuple[EvidenceV2, ...],
    catalog: CatalogV2,
    capabilities: CapabilitySnapshot,
    *,
    allow_network: bool = False,
    allow_user_scope: bool = False,
    now: datetime | None = None,
    ttl: timedelta = timedelta(hours=1),
) -> PlanV2:
    """Build a canonical, read-only plan bound to the current repository state."""

    repository_root = _validated_root(root)
    created_at = _aware_utc(now)
    if ttl <= timedelta(0) or ttl > timedelta(days=7):
        raise ValidationError("plan TTL must be positive and no longer than seven days")
    ordered_evidence = tuple(
        sorted(
            evidence,
            key=lambda item: (item.type, item.key, item.source, item.detail, item.strength),
        )
    )
    recommendations = recommend(
        catalog,
        ordered_evidence,
        capabilities,
        allow_network=allow_network,
        allow_user_scope=allow_user_scope,
    )
    tools_by_id = {tool.id: tool for tool in catalog}
    actions: list[ActionV2] = []
    for item in recommendations:
        if not item.actionable or "install" not in item.allowed_operations:
            continue
        tool = tools_by_id[item.tool_id]
        actions.append(
            ActionV2(
                id=f"a{len(actions) + 1:04d}",
                operation=ActionOperation.INSTALL,
                tool_id=tool.id,
                tool_version=tool.version,
                install_scope=tool.install_scope,
                permissions=tool.permissions,
                evidence=item.evidence,
                confidence=item.confidence,
                why=item.why,
                steps=(tool.install,),
                verify=(tool.verify,),
                rollback=(tool.rollback,),
                required_env=tool.required_env,
            )
        )
    return build_explicit_plan_v2(
        repository_root,
        catalog,
        capabilities,
        tuple(actions),
        now=created_at,
        ttl=ttl,
    )


def build_explicit_plan_v2(
    root: str | Path,
    catalog: CatalogV2,
    capabilities: CapabilitySnapshot,
    actions: tuple[ActionV2, ...] | list[ActionV2],
    *,
    now: datetime | None = None,
    ttl: timedelta = timedelta(hours=1),
) -> PlanV2:
    repository_root = _validated_root(root)
    created_at = _aware_utc(now)
    if ttl <= timedelta(0) or ttl > timedelta(days=7):
        raise ValidationError("plan TTL must be positive and no longer than seven days")
    catalog_digest = _catalog_digest(catalog)
    capability_digest = _capability_digest(capabilities)
    _validate_action_contracts(tuple(actions), catalog)
    binding = _repository_binding(repository_root)
    draft = PlanV2(
        plan_id="0" * 64,
        repository=binding,
        catalog_digest=catalog_digest,
        capability_digest=capability_digest,
        catalog_tools={tool.id: tool.version for tool in catalog},
        actions=tuple(actions),
        created_at=created_at,
        expires_at=created_at + ttl,
    )
    return draft.model_copy(update={"plan_id": calculate_plan_id(draft)})


def calculate_plan_id(plan: PlanV2) -> str:
    payload = plan.model_dump(mode="json")
    payload.pop("plan_id", None)
    return sha256(_canonical_json(payload)).hexdigest()


def write_plan_v2(plan: PlanV2, path: str | Path) -> Path:
    target = Path(path)
    payload = json.dumps(
        plan.model_dump(mode="json"),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    atomic_write_text(target, payload + "\n")
    return target


def read_plan_v2(path: str | Path) -> PlanV2:
    target = Path(path)
    try:
        if target.stat().st_size > 10 * 1024 * 1024:
            raise ValidationError("plan exceeds ten MiB")
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValidationError("plan root must be an object")
        return PlanV2.model_validate(raw)
    except FileNotFoundError as exc:
        raise ValidationError(f"plan not found: {target}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid plan: {exc}") from exc


def validate_plan_binding(
    plan: PlanV2,
    root: str | Path,
    catalog: CatalogV2,
    capabilities: CapabilitySnapshot,
    *,
    now: datetime | None = None,
) -> None:
    """Reject a plan if any security-relevant input changed after planning."""

    current_time = _aware_utc(now)
    if calculate_plan_id(plan) != plan.plan_id:
        raise StalePlanError("plan digest does not match its canonical content")
    if current_time >= plan.expires_at:
        raise StalePlanError("plan has expired")
    if _catalog_digest(catalog) != plan.catalog_digest:
        raise StalePlanError("catalog digest changed after planning")
    current_tools = {tool.id: tool.version for tool in catalog}
    if current_tools != plan.catalog_tools:
        raise StalePlanError("catalog tool versions changed after planning")
    try:
        _validate_action_contracts(plan.actions, catalog)
    except ValidationError as exc:
        raise StalePlanError(str(exc)) from exc
    if _capability_digest(capabilities) != plan.capability_digest:
        raise StalePlanError("capability inventory changed after planning")

    current = _repository_binding(_validated_root(root))
    if current.identity != plan.repository.identity:
        raise StalePlanError("repository identity changed after planning")
    if current.content_digest != plan.repository.content_digest:
        raise StalePlanError("repository content changed after planning")
    if current.git_head != plan.repository.git_head:
        raise StalePlanError("Git HEAD changed after planning")
    if current.dirty_digest != plan.repository.dirty_digest:
        raise StalePlanError("Git working-tree state changed after planning")


def _validated_root(root: str | Path) -> Path:
    selected = Path(root)
    if selected.is_symlink():
        raise ValidationError("repository root must not be a symbolic link")
    try:
        resolved = selected.resolve(strict=True)
    except OSError as exc:
        raise ValidationError("repository root does not exist") from exc
    if not resolved.is_dir():
        raise ValidationError("repository root must be a directory")
    return resolved


def _validate_action_contracts(actions: tuple[ActionV2, ...], catalog: CatalogV2) -> None:
    by_id = {tool.id: tool for tool in catalog}
    for action in actions:
        tool = by_id.get(action.tool_id)
        if tool is None or action.tool_version != tool.version:
            raise ValidationError(f"action {action.id} has no exact catalog contract")
        if (
            action.install_scope != tool.install_scope
            or action.permissions != tool.permissions
            or action.required_env != tool.required_env
        ):
            raise ValidationError(f"action {action.id} changes catalog security metadata")
        if action.operation is ActionOperation.INSTALL:
            expected = ((tool.install,), (tool.verify,), (tool.rollback,))
        elif action.operation in {ActionOperation.ADOPT, ActionOperation.VERIFY}:
            expected = ((), (tool.verify,), ())
        elif action.operation is ActionOperation.REMOVE:
            expected = ((tool.rollback,), (), (tool.install,))
        else:
            raise ValidationError(
                f"action {action.id} uses unsupported operation {action.operation.value}"
            )
        if (action.steps, action.verify, action.rollback) != expected:
            raise ValidationError(f"action {action.id} command contract differs from the catalog")


def _aware_utc(value: datetime | None) -> datetime:
    selected = value or datetime.now(UTC)
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise ValidationError("plan timestamps must be timezone-aware")
    return selected.astimezone(UTC)


def _catalog_digest(catalog: CatalogV2) -> str:
    actual = sha256(catalog.raw_bytes).hexdigest()
    if actual != catalog.digest:
        raise ValidationError("catalog object digest does not match its source bytes")
    return actual


def _capability_digest(capabilities: CapabilitySnapshot) -> str:
    return sha256(_canonical_json(capabilities.model_dump(mode="json"))).hexdigest()


def _repository_binding(root: Path) -> RepositoryBinding:
    git_head, dirty_digest = _git_binding(root)
    return RepositoryBinding(
        root=".",
        identity=repository_identity(root),
        content_digest=_repository_content_digest(root),
        git_head=git_head,
        dirty_digest=dirty_digest,
    )


def _repository_content_digest(root: Path) -> str:
    digest = sha256()
    files_seen = 0
    bytes_seen = 0
    stack: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath("."))]
    while stack:
        directory, relative_directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ValidationError(f"cannot read repository entry: {relative_directory}") from exc
        child_directories: list[tuple[Path, PurePosixPath]] = []
        for entry in entries:
            relative = (
                PurePosixPath(entry.name)
                if relative_directory == PurePosixPath(".")
                else relative_directory / entry.name
            )
            if entry.name in _IGNORED_DIRECTORIES:
                continue
            if relative.parts and relative.parts[0] == ".toolbelt":
                continue
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ValidationError(f"cannot inspect repository entry: {relative}") from exc
            if stat.S_ISDIR(metadata.st_mode):
                child_directories.append((Path(entry.path), relative))
                continue
            files_seen += 1
            if files_seen > _MAX_BOUND_FILES:
                raise ValidationError("repository binding exceeds the file limit")
            encoded_path = relative.as_posix().encode("utf-8", errors="surrogateescape")
            digest.update(len(encoded_path).to_bytes(4, "big"))
            digest.update(encoded_path)
            if stat.S_ISLNK(metadata.st_mode):
                target = os.readlink(entry.path).encode("utf-8", errors="surrogateescape")
                digest.update(b"L")
                digest.update(len(target).to_bytes(4, "big"))
                digest.update(target)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValidationError(f"unsupported repository file type: {relative}")
            bytes_seen += metadata.st_size
            if bytes_seen > _MAX_BOUND_BYTES:
                raise ValidationError("repository binding exceeds the byte limit")
            digest.update(b"F")
            digest.update(metadata.st_size.to_bytes(8, "big"))
            try:
                with open(entry.path, "rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
            except OSError as exc:
                raise ValidationError(f"cannot read repository file: {relative}") from exc
        stack.extend(reversed(child_directories))
    return digest.hexdigest()


def _git_binding(root: Path) -> tuple[str | None, str | None]:
    head = _run_git(root, "rev-parse", "--verify", "HEAD")
    if head is None:
        return None, None
    status_output = _run_git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    )
    if status_output is None:
        return head.decode("utf-8", errors="replace").strip(), None
    filtered = []
    for record in status_output.split(b"\0"):
        if not record:
            continue
        path = record[3:] if len(record) >= 3 else record
        normalized = path.replace(b"\\", b"/")
        if normalized == b".toolbelt" or normalized.startswith(b".toolbelt/"):
            continue
        filtered.append(record)
    dirty = b"\0".join(filtered)
    return (
        head.decode("utf-8", errors="replace").strip(),
        sha256(dirty).hexdigest() if dirty else None,
    )


def _run_git(root: Path, *arguments: str) -> bytes | None:
    return _run_git_bytes(root, *arguments)


def _run_git_bytes(root: Path, *arguments: str) -> bytes | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or len(result.stdout) > 1024 * 1024:
        return None
    return result.stdout


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


__all__ = [
    "build_explicit_plan_v2",
    "build_plan_v2",
    "calculate_plan_id",
    "read_plan_v2",
    "validate_plan_binding",
    "write_plan_v2",
]
