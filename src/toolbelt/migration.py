from __future__ import annotations

import json
from pathlib import Path

from toolbelt.errors import ValidationError
from toolbelt.paths import repository_identity, resolve_owned_path
from toolbelt.state import atomic_write_text


def migrate_v1_candidate(
    root: str | Path,
    output: str | Path,
) -> tuple[Path, int]:
    repository_root = Path(root).resolve(strict=True)
    identity = repository_identity(repository_root)
    source = resolve_owned_path(
        repository_root,
        ".toolbelt/manifest.json",
        expected_root_identity=identity,
    )
    if not source.exists():
        raise ValidationError("v1 manifest not found at .toolbelt/manifest.json")
    try:
        if source.stat().st_size > 1024 * 1024:
            raise ValidationError("v1 manifest exceeds one MiB")
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid v1 manifest: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValidationError("source must be a Toolbelt schema_version 1 manifest")
    raw_tools = raw.get("tools", {})
    if not isinstance(raw_tools, dict):
        raise ValidationError("v1 manifest tools must be an object")

    selected_output = Path(output)
    if selected_output.is_absolute():
        try:
            relative_output = selected_output.resolve().relative_to(repository_root)
        except ValueError as exc:
            raise ValidationError("migration output must remain inside the repository") from exc
    else:
        relative_output = selected_output
    target = resolve_owned_path(
        repository_root,
        relative_output.as_posix(),
        expected_root_identity=identity,
    )
    lines = [
        "schema_version = 2",
        "enabled = false",
        "source_schema_version = 1",
        "",
        "# Review and convert these candidates into strict v2 catalog entries.",
    ]
    for tool_id, record in sorted(raw_tools.items()):
        if not isinstance(tool_id, str) or not isinstance(record, dict):
            raise ValidationError("v1 tool records must be named objects")
        lines.extend(
            (
                "[[candidate]]",
                f"tool_id = {json.dumps(tool_id, ensure_ascii=False)}",
                f"state = {json.dumps(str(record.get('state', 'unknown')), ensure_ascii=False)}",
                f"version = {json.dumps(str(record.get('catalog_version', 'unknown')), ensure_ascii=False)}",
                f"provenance = {json.dumps(str(record.get('provenance', 'unknown')), ensure_ascii=False)}",
                "enabled = false",
                "",
            )
        )
    atomic_write_text(target, "\n".join(lines).rstrip() + "\n")
    return target, len(raw_tools)


__all__ = ["migrate_v1_candidate"]
