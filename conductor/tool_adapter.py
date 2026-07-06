from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from conductor.config import HIGH_RISK_TRIGGERS, TASK_CLASSES


START = "<CONDUCTOR_TASK>"
END = "</CONDUCTOR_TASK>"
TASK_NAME_RE = re.compile(r"^[a-z0-9_]+$")


@dataclass(frozen=True)
class TaskEnvelope:
    schema_version: int
    task_name: str
    task_class: str
    risk_triggers: tuple[str, ...]
    owned_paths: tuple[str, ...]
    acceptance_checks: tuple[str, ...]
    new_task: bool


@dataclass(frozen=True)
class ToolRequest:
    kind: str
    tool_name: str
    requested_model: str | None
    task_name: str | None
    envelope: TaskEnvelope | None


def normalize_tool_request(payload: dict, schema: dict | None = None) -> ToolRequest:
    tool_name = str(payload.get("tool_name") or payload.get("name") or "")
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    kind = _kind(tool_name, tool_input)
    requested_model = _first_string(tool_input, ("model", "model_slug", "requested_model"))
    task_name = _first_string(tool_input, ("task_name", "name"))
    envelope = None
    if kind in {"spawn", "new_task", "feedback"}:
        envelope = extract_envelope(_prompt_text(tool_input))
        if envelope is not None:
            task_name = task_name or envelope.task_name
            if envelope.new_task:
                kind = "new_task" if kind == "feedback" else kind
            elif kind != "spawn":
                kind = "feedback"
    return ToolRequest(kind=kind, tool_name=tool_name, requested_model=requested_model, task_name=task_name, envelope=envelope)


def _kind(tool_name: str, tool_input: dict[str, Any]) -> str:
    lower = tool_name.lower()
    if lower.endswith("spawn_agent") or lower == "spawn_agent":
        return "spawn"
    if lower in {"assign_agent_task", "send_message", "send_agent_message"}:
        text = _prompt_text(tool_input)
        return "new_task" if START in text else "feedback"
    return "other"


def _first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _prompt_text(tool_input: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("message", "prompt", "task", "instructions", "content"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    items = tool_input.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "\n".join(parts)


def extract_envelope(text: str) -> TaskEnvelope | None:
    start = text.find(START)
    end = text.find(END, start + len(START))
    if start < 0 or end < 0:
        return None
    raw = text[start + len(START) : end].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _envelope_from_dict(data)


def _envelope_from_dict(data: dict) -> TaskEnvelope | None:
    try:
        schema_version = int(data.get("schema_version"))
        task_name = str(data.get("task_name"))
        task_class = str(data.get("task_class"))
        risk_triggers = tuple(str(item) for item in data.get("risk_triggers", ()))
        owned_paths = tuple(str(item) for item in data.get("owned_paths", ()))
        acceptance_checks = tuple(str(item) for item in data.get("acceptance_checks", ()))
        new_task = bool(data.get("new_task"))
    except (TypeError, ValueError):
        return None
    if schema_version != 1:
        return None
    if not TASK_NAME_RE.match(task_name):
        return None
    if task_class not in TASK_CLASSES:
        return None
    if any(trigger not in HIGH_RISK_TRIGGERS for trigger in risk_triggers):
        return None
    if not owned_paths or not acceptance_checks:
        return None
    return TaskEnvelope(schema_version, task_name, task_class, risk_triggers, owned_paths, acceptance_checks, new_task)
