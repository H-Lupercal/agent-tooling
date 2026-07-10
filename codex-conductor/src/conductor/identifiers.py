from __future__ import annotations

import hashlib
import re

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def bounded_identifier(value: str, *, prefix: str) -> str:
    """Preserve a valid provider id or replace it with a stable bounded digest."""

    if _IDENTIFIER.fullmatch(value):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}-{digest}"


def derived_identifier(prefix: str, value: str) -> str:
    """Create a stable derived id without overflowing the public id contract."""

    return bounded_identifier(f"{prefix}-{value}", prefix=prefix)
