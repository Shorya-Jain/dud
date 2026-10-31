"""Read NVIDIA XID errors from the kernel log.

Only XID lines are kept. Process IDs and process names are removed, because
they can show what the renter runs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import missing, ok
from .common import short_bus

SRC = "kernel_log"
REF = "kernel_log"
REDACTIONS = ["non_xid_lines", "pid", "process_name"]

_XID = re.compile(r"NVRM: Xid \(PCI:([0-9A-Fa-f]{4}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})[^)]*\): (\d+),\s*(.*)$")
_TS = re.compile(r"^\[\s*(\d+\.\d+)\]")
_PROC = re.compile(r"\b(?:pid|name)=(?:'[^']*'|<[^>]*>|[^,]*),\s*")

_ATTEMPTS = (["dmesg"], ["journalctl", "-k", "--no-pager", "-o", "short-monotonic"])


@dataclass
class KernelLog:
    field: dict          # For host.kernel_log: which command worked, or why none did.
    events: list | None  # None when the log could not be read.
    result: object       # The CmdResult that gave the events (or the first attempt).
    text: str            # Filtered raw output (XID lines only).


def parse(text: str) -> list:
    events = []
    for line in text.splitlines():
        m = _XID.search(line)
        if not m:
            continue
        ts = _TS.match(line)
        events.append({
            "xid": int(m.group(2)),
            "pci": m.group(1).lower(),
            "uptime_s": float(ts.group(1)) if ts else None,
            "message": _PROC.sub("", m.group(3)).strip(),
        })
    return events


def format_event(e: dict) -> str:
    ts = f"[{e['uptime_s']:.6f}] " if e["uptime_s"] is not None else ""
    return f"{ts}NVRM: Xid (PCI:{e['pci']}): {e['xid']}, {e['message']}"


def _usable(result) -> bool:
    out = result.stdout.strip()
    return result.ok and bool(out) and "No entries" not in out and "No journal files" not in out


def collect(probe) -> KernelLog:
    results = []
    for argv in _ATTEMPTS:
        r = probe.run(argv)
        results.append(r)
        if _usable(r):
            events = parse(r.stdout)
            return KernelLog(ok(argv[0], SRC, REF), events, r, "\n".join(format_event(e) for e in events))
    if any(r.failure == "permission" for r in results):
        status, reason = "blocked", "permission_denied"
    elif any(r.ok for r in results):
        status, reason = "blocked", "kernel_log_empty"
    elif all(r.failure == "not_found" for r in results):
        status, reason = "error", "command_not_found"
    else:
        status, reason = "error", "command_failed"
    lines = [(r.stderr.strip().splitlines() or [r.failure or "empty output"])[0] for r in results]
    detail = "; ".join(line if line.startswith(r.argv[0]) else f"{r.argv[0]}: {line}"
                       for r, line in zip(results, lines))
    return KernelLog(missing(status, SRC, reason, detail, REF), None, results[0], "")


def events_field(log: KernelLog, bus_id: str) -> dict:
    if log.events is None:
        return dict(log.field)
    pci = short_bus(bus_id)
    return ok([e for e in log.events if e["pci"] == pci], SRC, REF)
