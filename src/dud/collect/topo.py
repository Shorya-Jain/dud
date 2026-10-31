"""Parse `nvidia-smi topo -m` (the GPU connection matrix)."""
from __future__ import annotations

import re

from ..model import missing, ok
from .common import cmd_failure_field

SRC = "smi_topo"
REF = "smi_topo_m"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def parse(text: str) -> dict:
    header, rows = None, {}
    for line in _ANSI.sub("", text).splitlines():
        if not line.strip():
            if rows:
                break
            continue
        if line.strip().startswith("Legend"):
            break
        # Cells are tab-separated. Some rows have double tabs, so drop empty cells.
        cells = [c.strip() for c in line.split("\t") if c.strip()]
        if header is None:
            header = cells
            continue
        rows[cells[0]] = dict(zip(header, cells[1:]))
    if not header or not rows:
        raise ValueError("no connection matrix in the output")
    return {"columns": header, "rows": rows}


def field(result) -> dict:
    if not result.ok:
        return cmd_failure_field(result, SRC, REF)
    try:
        return ok(parse(result.stdout), SRC, REF)
    except ValueError as e:
        return missing("error", SRC, "parse_failed", str(e), REF)
