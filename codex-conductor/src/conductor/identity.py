from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from conductor.capabilities import contract_digest, contract_mode, load_contract
from conductor.config import Ladder, config_digest, load_config
from conductor.errors import StateError
from conductor.rollout import SessionMeta, find_rollout, read_session_meta
from conductor.schemas import Provider, RunContext

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class Caller:
    run_id: str | None
    thread_id: str | None
    depth: int
    tier_index: int | None
    model: str
    effort: str = ""


@dataclass(frozen=True)
class IdentityResolution:
    caller: Caller
    posture: Literal["known", "deny", "observe", "degraded"]
    reason: str


def resolve_caller(payload: dict, ladder: Ladder, sessions_root: Path) -> Caller:
    model = str(payload.get("model") or "")
    effort = str(
        payload.get("reasoning_effort") or payload.get("model_reasoning_effort") or ""
    )
    tier = ladder.tier_index_for_model(model)
    thread_id = _identifier_or_none(
        payload.get("thread_id") or payload.get("agent_thread_id")
    )
    run_id = _identifier_or_none(payload.get("root_thread_id") or payload.get("run_id"))
    transcript = payload.get("agent_transcript_path") or payload.get("transcript_path")
    depth = 0
    if transcript:
        path = Path(transcript)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            meta = read_session_meta(path)
            thread_id = thread_id or _identifier_or_none(meta.thread_id)
            current_parent = _identifier_or_none(meta.parent_thread_id)
            if meta.thread_source == "subagent":
                depth = 1
            hops = 0
            while current_parent and hops < 10:
                parent_path = find_rollout(current_parent, sessions_root)
                if parent_path is None:
                    run_id = run_id or current_parent
                    break
                parent = read_session_meta(parent_path)
                if parent.parent_thread_id:
                    depth += 1
                else:
                    run_id = run_id or _identifier_or_none(parent.thread_id)
                    break
                current_parent = _identifier_or_none(parent.parent_thread_id)
                hops += 1
            if not current_parent and meta.parent_thread_id is None:
                run_id = run_id or _identifier_or_none(meta.thread_id)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return Caller(
        run_id=run_id,
        thread_id=thread_id,
        depth=depth,
        tier_index=tier,
        model=model,
        effort=effort,
    )


def resolve_identity(
    payload: dict, ladder: Ladder, sessions_root: Path
) -> IdentityResolution:
    caller = resolve_caller(payload, ladder, sessions_root)
    if caller.run_id is None or caller.thread_id is None:
        posture = ladder.policy.unknown_identity
        return IdentityResolution(caller, posture, "caller identity is unknown")
    if caller.tier_index is None:
        posture = ladder.policy.unknown_model
        return IdentityResolution(caller, posture, "caller model is unknown")
    return IdentityResolution(caller, "known", "caller identity and model are known")


def resolve_run_context(payload: dict) -> RunContext:
    if not isinstance(payload, dict):
        raise StateError("invalid run context: provider payload must be an object")
    raw_provider = payload.get("provider") or "codex"
    try:
        provider = Provider(raw_provider)
    except (TypeError, ValueError) as exc:
        raise StateError(f"invalid run context provider: {raw_provider!r}") from exc
    transcript = payload.get("transcript_path") or payload.get("agent_transcript_path")
    meta: SessionMeta | None = None
    # Only the Codex provider ships rollout-format transcripts that
    # read_session_meta() can parse. Claude Code transcripts use a different
    # JSONL schema (no per-line `payload` object) and supply run/thread ids
    # explicitly, so parsing their transcript here would wrongly abort
    # SessionStart and prevent the store from ever being created.
    if transcript and provider is Provider.CODEX:
        try:
            meta = read_session_meta(Path(transcript))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise StateError(f"invalid run context transcript: {exc}") from exc

    explicit_run = payload.get("root_thread_id") or payload.get("run_id")
    explicit_thread = payload.get("thread_id") or payload.get("agent_thread_id")
    thread_id = explicit_thread or (meta.thread_id if meta else None)
    run_id = explicit_run
    if run_id is None and meta is not None and meta.parent_thread_id is None:
        run_id = meta.thread_id
    if run_id is None and meta is not None:
        run_id = meta.parent_thread_id

    contract_name = payload.get("provider_contract") or f"{provider}-current"
    try:
        contract = load_contract(str(contract_name))
    except Exception as exc:
        raise StateError(f"invalid run context provider contract: {exc}") from exc
    if contract.provider is not provider:
        raise StateError(
            "invalid run context provider contract: "
            f"contract provider {contract.provider.value!r} does not match {provider.value!r}"
        )
    installed_digest = contract_digest(contract)
    digest = payload.get("contract_digest") or installed_digest
    if digest != installed_digest:
        raise StateError("invalid run context provider contract: contract digest drift")
    mode = payload.get("mode") or contract_mode(contract)
    config_hash = payload.get("config_digest")
    if config_hash is None:
        try:
            config_hash = config_digest(load_config())
        except Exception as exc:
            raise StateError(f"invalid run context configuration: {exc}") from exc
    now = datetime.now(UTC)
    try:
        return RunContext.model_validate(
            {
                "provider": provider,
                "run_id": run_id,
                "thread_id": thread_id,
                "root_model": payload.get("root_model") or payload.get("model"),
                "model_source": payload.get("model_source") or "provider",
                "provider_contract": contract.contract_name,
                "contract_digest": digest,
                "mode": mode,
                "generation": payload.get("generation", 1),
                "started_at": payload.get("started_at", now),
                "heartbeat_at": payload.get("heartbeat_at", now),
                "config_digest": config_hash,
            }
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise StateError(f"invalid run context: {exc}") from exc


def write_run_context(path: Path, context: RunContext) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(context.model_dump(mode="json"), handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except OSError as exc:
        raise StateError(f"cannot persist run context {destination}: {exc}") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def read_run_context(path: Path) -> RunContext:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        return RunContext.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise StateError(f"cannot read run context {source}: {exc}") from exc


def _identifier_or_none(value: object) -> str | None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        return None
    return value
