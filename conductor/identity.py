from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from conductor.config import Ladder
from conductor.rollout import find_rollout, read_session_meta


@dataclass(frozen=True)
class Caller:
    run_id: str | None
    thread_id: str | None
    depth: int
    tier_index: int | None
    model: str


def resolve_caller(payload: dict, ladder: Ladder, sessions_root: Path) -> Caller:
    model = str(payload.get("model") or "")
    tier = ladder.tier_index_for_model(model)
    thread_id = payload.get("thread_id") or payload.get("agent_thread_id")
    run_id = payload.get("root_thread_id") or payload.get("run_id")
    transcript = payload.get("agent_transcript_path") or payload.get("transcript_path")
    depth = 0
    if transcript:
        path = Path(transcript)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            meta = read_session_meta(path)
            thread_id = thread_id or meta.thread_id
            current_parent = meta.parent_thread_id
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
                    run_id = run_id or parent.thread_id
                    break
                current_parent = parent.parent_thread_id
                hops += 1
        except (OSError, ValueError):
            pass
    return Caller(run_id=str(run_id) if run_id else None, thread_id=str(thread_id) if thread_id else None, depth=depth, tier_index=tier, model=model)
