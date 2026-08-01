"""Shared rendering helpers."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any


def esc(value: Any) -> str:
    """HTML-escape a render value (defense against untrusted text)."""
    return html.escape(str(value), quote=True)


def fmt_dt(value: datetime | None) -> str:
    """Render a timestamp in UTC (deterministic across machines)."""
    if value is None:
        return "—"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M")


def fmt_dt_iso(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.isoformat().replace("+00:00", "Z")


def hash_short(value: str) -> str:
    """Short display form of a sha256 digest (full value stays in the DOM)."""
    if value.startswith("sha256:") and len(value) > 20:
        return f"{value[:13]}…{value[-8:]}"
    return value
