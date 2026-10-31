"""Parse `nvidia-smi -q -x` output into Fields.

The registry server parses the same raw XML with the same rules (in
TypeScript), so keep these rules simple. The parser accepts raw XML and XML
after ids.redact_smi_xml(); both give the same card IDs.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .. import ids
from ..model import missing, ok
from .common import norm_bus

SRC = "smi_xml"
REF = "smi_q_x"

_NUM = re.compile(r"^(-?\d+(?:\.\d+)?)\s*([A-Za-z%()/]*)$")
_TRUE = {"yes", "enabled", "active"}
_FALSE = {"no", "disabled", "not active"}
_HIST_KEYS = ("max", "high", "partial", "low", "none")


class SmiParseError(ValueError):
    pass


def _raw(el, path: str) -> str | None:
    """Text at path. If the path stops at an element with only text (for
    example <remapped_rows>N/A</remapped_rows>), return that text."""
    if el is None:
        return None
    node = el.find(path)
    if node is not None:
        return (node.text or "").strip()
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        anc = el.find("/".join(parts[:i]))
        if anc is not None:
            text = (anc.text or "").strip()
            return text if len(anc) == 0 and text else None
    return None


def classify(raw: str | None):
    """(status, reason) when raw is not a real value, else None."""
    if raw is None:
        return "not_supported", "not_in_output"
    low = raw.strip().strip("[]").strip().lower()
    if low in ("", "n/a", "na"):
        return "not_supported", "smi_na"
    if "insufficient permission" in low or "no permission" in low:
        return "blocked", "smi_insufficient_permissions"
    if "not supported" in low or "deprecated" in low:
        return "not_supported", "smi_not_supported"
    if "error" in low or "requires reset" in low:
        return "error", "smi_error"
    return None


def _first(el, *paths: str) -> str:
    if el is not None:
        for p in paths:
            if el.find(p) is not None:
                return p
    return paths[0]


def f_str(el, path: str) -> dict:
    raw = _raw(el, path)
    bad = classify(raw)
    return missing(bad[0], SRC, bad[1], raw, REF) if bad else ok(raw, SRC, REF)


def f_num(el, path: str, unit: str | None = None, as_float: bool = False) -> dict:
    raw = _raw(el, path)
    bad = classify(raw)
    if bad:
        return missing(bad[0], SRC, bad[1], raw, REF)
    m = _NUM.match(raw)
    if not m or (unit is not None and m.group(2) != unit):
        return missing("error", SRC, "parse_failed", raw, REF)
    n = float(m.group(1))
    return ok(n if as_float else int(n), SRC, REF)


def f_bool(el, path: str) -> dict:
    raw = _raw(el, path)
    bad = classify(raw)
    if bad:
        return missing(bad[0], SRC, bad[1], raw, REF)
    low = raw.lower()
    if low in _TRUE:
        return ok(True, SRC, REF)
    if low in _FALSE:
        return ok(False, SRC, REF)
    return missing("error", SRC, "parse_failed", raw, REF)


def _leaf(raw: str):
    if classify(raw):
        return None
    m = _NUM.match(raw)
    if m:
        return int(float(m.group(1)))
    low = raw.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return raw


def _detail(block, raw_if_missing: str | None) -> dict:
    """All counters in an ECC block as one object, for the record."""
    if block is None:
        bad = classify(raw_if_missing)
        return missing(bad[0], SRC, bad[1], raw_if_missing, REF)
    values, first_raw = {}, None
    for child in block:
        subs = list(child) or [child]
        for sub in subs:
            raw = (sub.text or "").strip()
            first_raw = raw if first_raw is None else first_raw
            key = sub.tag if sub is child else f"{child.tag}.{sub.tag}"
            values[key] = _leaf(raw)
    if not any(v is not None for v in values.values()):
        bad = classify(first_raw) or ("not_supported", "smi_na")
        return missing(bad[0], SRC, bad[1], first_raw, REF)
    return ok(values, SRC, REF)


def _sum(block, tags: list) -> dict:
    """Sum of counters. OK only when every counter has a number."""
    if not tags:
        return missing("not_supported", SRC, "not_in_output", None, REF)
    total = 0
    for tag in tags:
        f = f_num(block, tag)
        if f["status"] != "ok":
            return f
        total += f["value"]
    return ok(total, SRC, REF)


def _ecc_counts(gpu, tag: str) -> dict:
    block = gpu.find(f"ecc_errors/{tag}")
    if block is None:
        raw = _raw(gpu, f"ecc_errors/{tag}")
        bad = classify(raw)
        m = missing(bad[0], SRC, bad[1], raw, REF)
        return {"correctable": m, "uncorrectable": dict(m), "detail": dict(m)}
    if block.find("single_bit") is not None:  # Drivers before R450.
        corr, unc = f_num(block, "single_bit/total"), f_num(block, "double_bit/total")
    else:
        tags = [c.tag for c in block]
        corr = _sum(block, [t for t in tags if t.endswith("correctable") and "uncorrectable" not in t])
        unc = _sum(block, [t for t in tags if "uncorrectable" in t])
    return {"correctable": corr, "uncorrectable": unc, "detail": _detail(block, None)}


def _throttle(gpu) -> dict:
    block = gpu.find("clocks_event_reasons")
    if block is None:
        block = gpu.find("clocks_throttle_reasons")
    if block is None:
        return missing("not_supported", SRC, "not_in_output", None, REF)
    active, first_raw = [], None
    for child in block:
        raw = (child.text or "").strip()
        first_raw = raw if first_raw is None else first_raw
        if raw.lower() == "active":
            active.append(re.sub(r"^clocks_(event|throttle)_reason_", "", child.tag))
    if first_raw is not None and classify(first_raw):
        bad = classify(first_raw)
        return missing(bad[0], SRC, bad[1], first_raw, REF)
    return ok(active, SRC, REF)


def _card(raw: str | None, kind: str) -> dict:
    bad = classify(raw)
    if bad:
        return missing(bad[0], "derived", bad[1], raw, REF)
    if ids.is_marker(raw):
        return ok(ids.hash_from_marker(raw), "derived", REF)
    if not ids.is_real_id(raw):
        return missing("not_supported", "derived", "smi_na", raw, REF)
    return ok(ids.uuid_hash(raw) if kind == "uuid" else ids.serial_hash(raw), "derived", REF)


def _gpu(g) -> dict:
    power = g.find("gpu_power_readings")
    if power is None:
        power = g.find("power_readings")  # Drivers before R535.
    link = "pci/pci_gpu_link_info"
    remap = "remapped_rows"
    uuid_raw, serial_raw = _raw(g, "uuid"), _raw(g, "serial")

    identity = {
        "name": f_str(g, "product_name"),
        "architecture": f_str(g, "product_architecture"),
        "vbios": f_str(g, "vbios_version"),
        "board_part_number": f_str(g, "board_part_number"),
        "pci_device_id": f_str(g, "pci/pci_device_id"),
        "pci_subsystem_id": f_str(g, "pci/pci_sub_system_id"),
        "inforom_image": f_str(g, "inforom_version/img_version"),
        "gsp_firmware": f_str(g, "gsp_firmware_version"),
        "memory_total_mib": f_num(g, "fb_memory_usage/total", "MiB"),
        "power_limit_default_w": f_num(power, "default_power_limit", "W", True),
        "power_limit_current_w": f_num(
            power, _first(power, "current_power_limit", "enforced_power_limit", "power_limit"), "W", True),
        "power_limit_max_w": f_num(power, "max_power_limit", "W", True),
        "pcie": {
            "gen_max": f_num(g, f"{link}/pcie_gen/max_link_gen"),
            "gen_current": f_num(g, f"{link}/pcie_gen/current_link_gen"),
            "width_max": f_num(g, f"{link}/link_widths/max_link_width", "x"),
            "width_current": f_num(g, f"{link}/link_widths/current_link_width", "x"),
        },
        "mig_mode": f_bool(g, "mig_mode/current_mig"),
        "persistence_mode": f_bool(g, "persistence_mode"),
        "compute_mode": f_str(g, "compute_mode"),
        "max_clocks": {
            "sm_mhz": f_num(g, "max_clocks/sm_clock", "MHz"),
            "mem_mhz": f_num(g, "max_clocks/mem_clock", "MHz"),
        },
        "fabric_state": f_str(g, "fabric/state"),
    }
    history = {
        "ecc_mode": f_bool(g, "ecc_mode/current_ecc"),
        "ecc_mode_pending": f_bool(g, "ecc_mode/pending_ecc"),
        "ecc": {
            "volatile": _ecc_counts(g, "volatile"),
            "aggregate": _ecc_counts(g, "aggregate"),
            "aggregate_sram_sources": _detail(g.find("ecc_errors/aggregate_uncorrectable_sram_sources"),
                                              _raw(g, "ecc_errors/aggregate_uncorrectable_sram_sources")),
        },
        "row_remap": {
            "correctable": f_num(g, f"{remap}/remapped_row_corr"),
            "uncorrectable": f_num(g, f"{remap}/remapped_row_unc"),
            "pending": f_bool(g, f"{remap}/remapped_row_pending"),
            "failed": f_bool(g, f"{remap}/remapped_row_failure"),
            "bank_availability": {
                k: f_num(g, f"{remap}/remapped_row_histogram/row_remap_histogram_{k}", "bank(s)")
                for k in _HIST_KEYS
            },
        },
        "retired_pages": {
            "correctable": f_num(g, "retired_pages/multiple_single_bit_retirement/retired_count"),
            "uncorrectable": f_num(g, "retired_pages/double_bit_retirement/retired_count"),
            "pending": f_bool(g, _first(g, "retired_pages/pending_retirement", "retired_pages/pending_blacklist")),
        },
        "xid_events": None,  # The collector adds this from the kernel log.
    }
    snapshot = {
        "gpu_temp_c": f_num(g, "temperature/gpu_temp", "C"),
        "memory_temp_c": f_num(g, "temperature/memory_temp", "C"),
        "power_draw_w": f_num(power, _first(power, "power_draw", "average_power_draw", "instant_power_draw"),
                              "W", True),
        "performance_state": f_str(g, "performance_state"),
        "reset_required": f_bool(g, "gpu_reset_status/reset_required"),
        "pcie_replay_count": f_num(g, "pci/replay_counter"),
        "throttle_reasons_active": _throttle(g),
    }
    return {
        "bus_id": norm_bus(g.get("id") or _raw(g, "pci/pci_bus_id") or ""),
        "uuid": uuid_raw,
        "serial": serial_raw,
        "card": {"uuid_sha256": _card(uuid_raw, "uuid"), "serial_sha256": _card(serial_raw, "serial")},
        "identity": identity,
        "history": history,
        "snapshot": snapshot,
    }


def parse(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError as e:
        raise SmiParseError(str(e))
    if root.tag != "nvidia_smi_log":
        raise SmiParseError(f"root element is {root.tag}, not nvidia_smi_log")
    top = {
        "driver_version": f_str(root, "driver_version"),
        "cuda_version": f_str(root, "cuda_version"),
        "timestamp": f_str(root, "timestamp"),
        "attached_gpus": f_num(root, "attached_gpus"),
    }
    return {"top": top, "gpus": [_gpu(g) for g in root.findall("gpu")]}
