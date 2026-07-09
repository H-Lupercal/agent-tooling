from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from toolbelt.catalog import CatalogV2, load_catalog_v2
from toolbelt.errors import ValidationError
from toolbelt.paths import repository_identity, resolve_owned_path
from toolbelt.scanner import scan_repository
from toolbelt.schemas import CapabilitySnapshot
from toolbelt.state import STATE_SCHEMA_VERSION, load_declaration


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    code: str
    ok: bool
    severity: str
    message: str


def doctor_report(
    *,
    root: str | Path | None = None,
    capabilities: CapabilitySnapshot | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    checks: list[DoctorCheck] = []
    catalog: CatalogV2 | None = None
    distribution: dict[str, Any] = {
        "catalog_loaded": False,
        "catalog_tools": 0,
        "version": "unknown",
    }
    try:
        catalog = load_catalog_v2()
        distribution["catalog_loaded"] = True
        distribution["catalog_tools"] = len(catalog)
        checks.append(DoctorCheck("DISTRIBUTION_CATALOG", True, "error", "bundled catalog loaded"))
    except Exception as exc:
        checks.append(DoctorCheck("DISTRIBUTION_CATALOG", False, "error", str(exc)))
    try:
        distribution["version"] = metadata.version("toolbelt-ai")
        checks.append(DoctorCheck("DISTRIBUTION_METADATA", True, "error", "package metadata loaded"))
    except metadata.PackageNotFoundError:
        checks.append(DoctorCheck("DISTRIBUTION_METADATA", False, "error", "package metadata unavailable"))

    project: dict[str, Any] | None = None
    if root is not None:
        selected_root = Path(root)
        try:
            selected_root = selected_root.resolve(strict=True)
            identity = repository_identity(selected_root)
            scan = scan_repository(selected_root)
            project = {
                "root": str(selected_root),
                "identity": identity,
                "files_scanned": scan.files_scanned,
                "warnings": [asdict(warning) for warning in scan.warnings],
            }
            checks.append(DoctorCheck("PROJECT_SCAN", True, "error", "repository scan completed"))
            if os.access(selected_root, os.W_OK):
                checks.append(DoctorCheck("PROJECT_WRITABLE", True, "warning", "repository is writable"))
            else:
                checks.append(DoctorCheck("PROJECT_WRITABLE", False, "warning", "repository is read-only"))
            declaration = load_declaration(selected_root)
            if declaration is None:
                checks.append(DoctorCheck("DECLARATION", False, "warning", "no v2 declaration exists"))
            else:
                valid_identity = declaration.repository_identity == identity
                valid_catalog = catalog is not None and declaration.catalog_digest == catalog.digest
                checks.append(
                    DoctorCheck(
                        "DECLARATION",
                        valid_identity and valid_catalog,
                        "error",
                        "declaration is current"
                        if valid_identity and valid_catalog
                        else "declaration identity or catalog digest is stale",
                    )
                )
            state_path = resolve_owned_path(selected_root, ".toolbelt/state.sqlite3")
            state = inspect_state(state_path)
            project["state"] = state
            if state["exists"]:
                checks.append(
                    DoctorCheck(
                        "STATE_SCHEMA",
                        state["schema_version"] == STATE_SCHEMA_VERSION and state["integrity"] == "ok",
                        "error",
                        "state database schema and integrity are valid",
                    )
                )
            else:
                checks.append(DoctorCheck("STATE_SCHEMA", True, "warning", "state database not initialized"))
            if capabilities is not None:
                known = capabilities.status.value == "known"
                checks.append(
                    DoctorCheck(
                        "CAPABILITY_INVENTORY",
                        known,
                        "warning",
                        "provider capability inventory is known"
                        if known
                        else "provider capability inventory is unknown",
                    )
                )
        except Exception as exc:
            checks.append(DoctorCheck("PROJECT", False, "error", str(exc)))

    errors = [check for check in checks if not check.ok and check.severity == "error"]
    warnings = [check for check in checks if not check.ok and check.severity == "warning"]
    ready = not errors and (not strict or not warnings)
    return {
        "ready": ready,
        "strict": strict,
        "distribution": distribution,
        "project": project,
        "checks": [asdict(check) for check in checks],
        "error_count": len(errors),
        "warning_count": len(warnings),
    }


def status_report(root: str | Path) -> dict[str, Any]:
    selected_root = Path(root).resolve(strict=True)
    declaration = load_declaration(selected_root)
    state_path = resolve_owned_path(selected_root, ".toolbelt/state.sqlite3")
    return {
        "repository_identity": repository_identity(selected_root),
        "declaration": None
        if declaration is None
        else declaration.model_dump(mode="json"),
        "state": inspect_state(state_path),
    }


def inspect_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "schema_version": None,
            "integrity": None,
            "transaction_count": 0,
            "incomplete_transactions": [],
        }
    if path.is_symlink():
        raise ValidationError("state database must not be a symbolic link")
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        try:
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            integrity = str(connection.execute("PRAGMA integrity_check(1)").fetchone()[0])
            count = int(connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
            rows = connection.execute(
                """
                SELECT transaction_id, plan_id, state, created_at, updated_at, error
                FROM transactions
                WHERE state NOT IN ('succeeded', 'rolled_back', 'rollback_failed')
                ORDER BY created_at
                """
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ValidationError(f"cannot inspect state database: {exc}") from exc
    return {
        "exists": True,
        "schema_version": schema_version,
        "integrity": integrity,
        "transaction_count": count,
        "incomplete_transactions": [dict(row) for row in rows],
    }


__all__ = ["doctor_report", "inspect_state", "status_report"]
