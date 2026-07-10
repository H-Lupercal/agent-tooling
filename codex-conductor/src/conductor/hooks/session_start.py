from __future__ import annotations

import argparse

from conductor.capabilities import contract_digest, contract_mode, load_contract
from conductor.config import config_digest, load_config
from conductor.errors import ConductorError, StateError
from conductor.hooks.common import log_error, read_payload, write_json
from conductor.identity import resolve_run_context, write_run_context
from conductor.ledger import run_state_dir, store_path
from conductor.schemas import RunContext
from conductor.store import Store


def handle(
    payload: dict,
    run_id: str | None = None,
    *,
    provider_name: str | None = None,
    store: Store | None = None,
) -> RunContext:
    """Validate and atomically initialize a leased v2 run."""

    from conductor.providers import get_provider

    name = provider_name or str(payload.get("provider") or "codex")
    provider = get_provider(name)
    config = load_config()
    caller = provider.resolve_caller(payload, config)
    resolved_run_id = run_id or provider.session_run_id(payload) or caller.run_id
    if resolved_run_id is None:
        raise StateError("SessionStart did not expose a bounded run id")
    root_model = payload.get("root_model") or payload.get("model") or caller.model
    thread_id = caller.thread_id or resolved_run_id
    contract = load_contract(f"{provider.name}-current")
    context = resolve_run_context(
        {
            **payload,
            "provider": provider.name,
            "run_id": resolved_run_id,
            "thread_id": thread_id,
            "root_model": root_model,
            "model_source": "provider" if payload.get("model") else "operator",
            "provider_contract": contract.contract_name,
            "contract_digest": contract_digest(contract),
            "mode": contract_mode(contract).value,
            "generation": payload.get("generation", 1),
            "config_digest": config_digest(config),
        }
    )
    database = store or Store(
        store_path(), busy_timeout_ms=config.policy.busy_timeout_ms
    )
    database.create_run(
        context.run_id,
        provider=context.provider.value,
        generation=context.generation,
        mode=context.mode.value,
        lease_seconds=max(300, config.policy.reservation_ttl_seconds * 2),
        owner_id=context.thread_id,
        context=context.model_dump(mode="json"),
    )
    write_run_context(run_state_dir(context.run_id) / "run_context.json", context)
    return context


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        payload = read_payload()
        handle(payload, provider_name=args.provider)
        write_json({})
    except (ConductorError, OSError, ValueError) as exc:
        log_error("session_start", exc)
        write_json({"conductor": {"ready": False, "error": type(exc).__name__}})
    except BaseException as exc:
        log_error("session_start", exc)
        write_json({"conductor": {"ready": False, "error": "InternalError"}})
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
