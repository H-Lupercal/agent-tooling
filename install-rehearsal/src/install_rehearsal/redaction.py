"""Minimize inherited environment data and redact secret-shaped output."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_ALLOWED_ENVIRONMENT = {
    "COMSPEC",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TERM",
    "TMP",
    "TMPDIR",
    "TEMP",
    "WINDIR",
}
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.IGNORECASE)
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_.-]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)[A-Z0-9_.-]*)=([^\s]+)"
)
_BEARER = re.compile(r"(?i)(Authorization:\s*Bearer\s+)([^\s]+)")
_SECRET_OPTION = re.compile(r"(?i)^--?(?:api[-_]?key|token|secret|password|credential|auth)$")
_SECRET_INLINE = re.compile(
    r"(?i)^(--?(?:api[-_]?key|token|secret|password|credential|auth))=(.*)$"
)


def build_child_environment(
    parent: Mapping[str, str], overlay: Mapping[str, str]
) -> dict[str, str]:
    inherited = {
        key: value
        for key, value in parent.items()
        if key.upper() in _ALLOWED_ENVIRONMENT and not _SECRET_NAME.search(key)
    }
    inherited.update(overlay)
    return dict(sorted(inherited.items()))


def redact_text(text: str) -> str:
    redacted = _ASSIGNMENT.sub(r"\1=[REDACTED]", text)
    return _BEARER.sub(r"\1[REDACTED]", redacted)


def redact_argv(argv: Sequence[str]) -> tuple[str, ...]:
    redacted: list[str] = []
    redact_next = False
    for argument in argv:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        inline = _SECRET_INLINE.match(argument)
        if inline:
            redacted.append(f"{inline.group(1)}=[REDACTED]")
        else:
            redacted.append(redact_text(argument))
            redact_next = bool(_SECRET_OPTION.match(argument))
    return tuple(redacted)
