from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None


class ManifestError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def manifest_path(root: Path) -> Path:
    return Path(root) / ".toolbelt" / "manifest.json"


def load_manifest(root: Path) -> dict:
    path = manifest_path(root)
    if not path.exists():
        return {
            "schema_version": 1,
            "project_root": str(Path(root).resolve()),
            "created_at": "",
            "updated_at": "",
            "mode": "",
            "intent": {},
            "last_scan": {},
            "tools": {},
            "guard": {},
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"corrupt manifest: {path}; move it aside to re-init") from exc


@contextmanager
def _manifest_lock(tb: Path):
    lock = tb / ".manifest.lock"
    start = time.time()
    if fcntl is not None:
        with lock.open("w", encoding="utf-8") as lock_f:
            while True:
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.time() - start > 5:
                        raise ManifestError("manifest lock timeout") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
    else:
        fd = None
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError as exc:
                try:
                    stale = (time.time() - lock.stat().st_mtime) > 30
                except OSError:
                    stale = False
                if stale:
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() - start > 5:
                    raise ManifestError("manifest lock timeout") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            except OSError:
                pass
            try:
                lock.unlink()
            except OSError:
                pass


def save_manifest(root: Path, data: dict) -> None:
    root = Path(root)
    tb = root / ".toolbelt"
    tb.mkdir(parents=True, exist_ok=True)
    with _manifest_lock(tb):
        data = dict(data)
        data.setdefault("schema_version", 1)
        data.setdefault("project_root", str(root.resolve()))
        if not data.get("created_at"):
            data["created_at"] = _now()
        data["updated_at"] = _now()
        fd, tmp_name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=str(tb))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tmp:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            os.replace(tmp_name, manifest_path(root))
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)


def upsert_tool(data: dict, tool_id: str, record: dict) -> dict:
    updated = dict(data)
    tools = dict(updated.get("tools") or {})
    tools[tool_id] = record
    updated["tools"] = tools
    return updated


def remove_tool_record(data: dict, tool_id: str) -> dict:
    updated = dict(data)
    tools = dict(updated.get("tools") or {})
    rec = dict(tools.get(tool_id) or {})
    rec["state"] = "removed"
    tools[tool_id] = rec
    updated["tools"] = tools
    return updated


def unmanaged_and_drift(data: dict, live: dict) -> dict:
    claimed: dict[str, set[str]] = {"claude_mcp": set(), "codex_mcp": set(), "claude_plugin": set()}
    name_claims: dict[tuple[str, str], list[str]] = {}
    drifted: list[str] = []
    for tool_id, rec in (data.get("tools") or {}).items():
        live_names = rec.get("live_names") or {}
        if rec.get("state") == "installed":
            for kind, name in live_names.items():
                if not name:
                    continue
                claimed.setdefault(kind, set()).add(name)
                name_claims.setdefault((kind, name), []).append(tool_id)
                if kind == "claude_mcp":
                    scopes = live.get("claude_mcp") or {}
                    if name not in set(scopes.get("project", [])) | set(scopes.get("local", [])) | set(scopes.get("user", [])):
                        drifted.append(tool_id)
                elif name not in set(live.get(kind) or []):
                    drifted.append(tool_id)

    unmanaged: list[str] = []
    for scope, names in (live.get("claude_mcp") or {}).items():
        for name in names:
            if name not in claimed.get("claude_mcp", set()):
                unmanaged.append(f"claude_mcp:{name}")
    for kind in ("codex_mcp", "claude_plugin"):
        for name in live.get(kind) or []:
            if name not in claimed.get(kind, set()):
                unmanaged.append(f"{kind}:{name}")

    duplicates: list[str] = []
    scopes = live.get("claude_mcp") or {}
    counts: dict[str, int] = {}
    for names in scopes.values():
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    duplicates.extend(f"claude_mcp:{name}" for name, count in sorted(counts.items()) if count >= 2)
    duplicates.extend(f"{kind}:{name}" for (kind, name), ids in sorted(name_claims.items()) if len(ids) >= 2)
    return {
        "unmanaged": sorted(set(unmanaged)),
        "drifted_missing": sorted(set(drifted)),
        "duplicates": sorted(set(duplicates)),
    }
