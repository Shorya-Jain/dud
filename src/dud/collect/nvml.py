"""Read NVML values. They fill gaps in nvidia-smi output and act as a cross-check.

NVML gives no raw text that the server can check, so the nvidia-smi XML stays
the main evidence. See docs/DESIGN.md.
"""
from __future__ import annotations

from ..model import missing, ok
from ..probe import NvmlFail
from .common import norm_bus

SRC = "nvml"
REF = "nvml_snapshot"
_FAIL = {
    "not_supported": ("not_supported", "nvml_not_supported"),
    "no_permission": ("blocked", "nvml_no_permission"),
    "missing": ("error", "nvml_missing"),
    "error": ("error", "nvml_error"),
}
_REMAP_KEYS = ("correctable", "uncorrectable", "pending", "failed")
_HIST_KEYS = ("max", "high", "partial", "low", "none")


def _fail_field(e: NvmlFail) -> dict:
    status, reason = _FAIL.get(e.kind, _FAIL["error"])
    return missing(status, SRC, reason, e.detail, REF)


def _map(f: dict, fn) -> dict:
    return ok(fn(f["value"]), SRC, REF) if f["status"] == "ok" else dict(f)


def collect(probe) -> dict:
    """Return {version, devices: {bus_id: {uuid, fields}}, snapshot, fail_field}.

    `fields` maps a path inside a GPU entry (for example
    "history.row_remap.pending") to a Field.
    """
    out = {"version": None, "devices": {}, "snapshot": {}, "fail_field": None}
    try:
        nv = probe.nvml()
    except NvmlFail as e:
        out["version"] = out["fail_field"] = _fail_field(e)
        out["snapshot"] = {"error": e.kind, "detail": e.detail}
        return out
    try:
        try:
            out["version"] = ok(nv.version(), SRC, REF)
        except NvmlFail as e:
            out["version"] = _fail_field(e)
        snapshot = {"nvml_version": out["version"]["value"], "devices": []}
        out["snapshot"] = snapshot
        for i in range(nv.count()):
            raw = {}

            def get(key):
                try:
                    raw[key] = nv.get(i, key)
                    return ok(raw[key], SRC, REF)
                except NvmlFail as e:
                    raw[key] = {"$error": e.kind, "detail": e.detail}
                    return _fail_field(e)

            bus, uuid = get("pci_bus_id"), get("uuid")
            mem, remap, hist, nvlink = get("memory_total_bytes"), get("remapped_rows"), get("bank_availability"), get("nvlink")
            snapshot["devices"].append(raw)
            fields = {
                "identity.memory_total_mib": _map(mem, lambda b: b // 1048576),
                "identity.nvlink": nvlink,
            }
            for k in _REMAP_KEYS:
                fields[f"history.row_remap.{k}"] = _map(remap, lambda v, k=k: v[k])
            for k in _HIST_KEYS:
                fields[f"history.row_remap.bank_availability.{k}"] = _map(hist, lambda v, k=k: v[k])
            if bus["status"] == "ok":
                out["devices"][norm_bus(bus["value"])] = {"uuid": uuid["value"], "fields": fields}
    except NvmlFail as e:
        out["fail_field"] = _fail_field(e)
        out["snapshot"]["error"] = e.kind
    finally:
        nv.shutdown()
    return out
