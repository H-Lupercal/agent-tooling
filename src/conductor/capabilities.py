from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files

from conductor.errors import UnsupportedCapabilityError
from conductor.schemas import (
    CapabilityContract,
    OperatingMode,
    ToolContract,
)


_CONTRACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class CapabilityResult:
    contract_name: str
    contract_digest: str
    mode: OperatingMode
    child_model_selectable: bool
    matched_operation: str | None
    reason: str


def load_contract(name: str) -> CapabilityContract:
    if not _CONTRACT_NAME.fullmatch(name):
        raise UnsupportedCapabilityError(f"invalid provider contract name: {name!r}")
    resource = files("conductor.assets").joinpath("contracts", f"{name}.json")
    try:
        raw = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise UnsupportedCapabilityError(f"unknown provider contract: {name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UnsupportedCapabilityError(
            f"cannot load provider contract {name}: {exc}"
        ) from exc
    try:
        return CapabilityContract.model_validate(raw)
    except ValueError as exc:
        raise UnsupportedCapabilityError(
            f"invalid provider contract {name}: {exc}"
        ) from exc


def contract_digest(contract: CapabilityContract) -> str:
    canonical = json.dumps(
        contract.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def negotiate(contract: CapabilityContract, payload: object) -> CapabilityResult:
    digest = contract_digest(contract)
    try:
        installed = load_contract(contract.contract_name)
    except UnsupportedCapabilityError:
        return _result(
            contract,
            digest,
            OperatingMode.UNSUPPORTED,
            False,
            None,
            "contract is not installed",
        )
    if contract_digest(installed) != digest:
        return _result(
            contract,
            digest,
            OperatingMode.UNSUPPORTED,
            False,
            None,
            "provider contract digest drift",
        )

    matched = [
        tool for tool in contract.tools if _matches_schema(payload, tool.input_schema)
    ]
    if len(matched) != 1:
        reason = "payload does not match the installed tool-input schema"
        if len(matched) > 1:
            reason = "payload ambiguously matches multiple installed tool-input schemas"
        return _result(
            contract,
            digest,
            OperatingMode.UNSUPPORTED,
            False,
            None,
            reason,
        )
    tool = matched[0]

    correlations = contract.correlation_fields
    has_identity = bool(correlations.run_id and correlations.child_id)
    has_lifecycle = bool(correlations.lifecycle_id)
    if not contract.hook_events or not has_identity:
        return _result(
            contract,
            digest,
            OperatingMode.UNSUPPORTED,
            False,
            tool.canonical_name.value,
            "required run or child identity is unavailable",
        )
    if not contract.can_block:
        return _result(
            contract,
            digest,
            OperatingMode.OBSERVE,
            False,
            tool.canonical_name.value,
            "provider exposes observations but cannot block operations",
        )
    if not has_lifecycle:
        return _result(
            contract,
            digest,
            OperatingMode.UNSUPPORTED,
            False,
            tool.canonical_name.value,
            "correlated lifecycle events are unavailable",
        )

    selector = contract.model_selector_path
    if selector is None:
        return _result(
            contract,
            digest,
            OperatingMode.ADMISSION,
            False,
            tool.canonical_name.value,
            "provider can block correlated work but exposes no child-model selector",
        )
    if not _schema_has_path(tool, selector):
        return _result(
            contract,
            digest,
            OperatingMode.UNSUPPORTED,
            False,
            tool.canonical_name.value,
            "declared child-model selector is absent from the tool-input schema",
        )
    return _result(
        contract,
        digest,
        OperatingMode.ROUTING,
        True,
        tool.canonical_name.value,
        "provider exposes an enforceable child-model selector and correlated lifecycle",
    )


def _result(
    contract: CapabilityContract,
    digest: str,
    mode: OperatingMode,
    selectable: bool,
    operation: str | None,
    reason: str,
) -> CapabilityResult:
    return CapabilityResult(
        contract_name=contract.contract_name,
        contract_digest=digest,
        mode=mode,
        child_model_selectable=selectable,
        matched_operation=operation,
        reason=reason,
    )


def _schema_has_path(tool: ToolContract, path: str) -> bool:
    schema: object = tool.input_schema
    for part in path.split("."):
        if not isinstance(schema, dict):
            return False
        properties = schema.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return False
        schema = properties[part]
    return True


def _matches_schema(value: object, schema: object) -> bool:
    if not isinstance(schema, dict):
        return False
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return False
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict):
            return False
        if any(name not in value for name in required):
            return False
        if schema.get("additionalProperties") is False and any(
            name not in properties for name in value
        ):
            return False
        return all(
            name not in value or _matches_schema(value[name], child_schema)
            for name, child_schema in properties.items()
        )
    if expected_type == "string":
        if not isinstance(value, str):
            return False
        if (
            isinstance(schema.get("minLength"), int)
            and len(value) < schema["minLength"]
        ):
            return False
        if (
            isinstance(schema.get("maxLength"), int)
            and len(value) > schema["maxLength"]
        ):
            return False
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            return False
    elif expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return False
    elif expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
    elif expected_type == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items")
        if item_schema is not None and not all(
            _matches_schema(item, item_schema) for item in value
        ):
            return False
    elif expected_type is not None:
        return False
    enum = schema.get("enum")
    return not isinstance(enum, list) or value in enum
