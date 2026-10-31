from __future__ import annotations

import re

from ..model import missing

_BUS = re.compile(r"^([0-9a-fA-F]+):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])$")


def norm_bus(bus: str) -> str:
    """'0000:18:00.0' or '00000000:18:00.0' -> '00000000:18:00.0'."""
    m = _BUS.match((bus or "").strip())
    if not m:
        return (bus or "").strip().lower()
    return f"{int(m.group(1), 16):08x}:{m.group(2).lower()}:{m.group(3).lower()}.{m.group(4)}"


def short_bus(bus: str) -> str:
    """'00000000:18:00.0' -> '0000:18:00' (the form in kernel XID lines)."""
    n = norm_bus(bus)
    return f"{n[4:8]}:{n[9:11]}:{n[12:14]}" if _BUS.match(n) else n


def cmd_failure_field(result, source: str, raw_ref: str | None) -> dict:
    status, reason = {
        "not_found": ("error", "command_not_found"),
        "permission": ("blocked", "permission_denied"),
        "timeout": ("error", "command_timeout"),
    }.get(result.failure, ("error", "command_failed"))
    detail = (result.stderr or "").strip().splitlines()
    return missing(status, source, reason, detail[0] if detail else None, raw_ref)
