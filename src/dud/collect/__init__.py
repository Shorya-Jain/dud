"""Collect identity, history and visibility for every GPU on the node."""
from __future__ import annotations

import json
import time

from .. import gpumodels, ids, model
from ..model import iter_fields, missing, ok
from . import host as host_mod
from . import kernel_log, smi_xml, topo
from . import nvml as nvml_mod
from .common import cmd_failure_field

_TOP_KEYS = ("driver_version", "cuda_version", "timestamp", "attached_gpus")
# On a known data center model, N/A for these reasons means "hidden", not "not supported".
_HIDDEN_REASONS = ("smi_na", "smi_not_supported")


class UnknownGpu(Exception):
    def __init__(self, missing_indices: list, available: list):
        super().__init__(f"unknown GPU index {missing_indices}")
        self.missing = missing_indices
        self.available = available


def collect(probe, *, mode: str, provider: str | None = None, gpu_indices: list | None = None,
            options: dict | None = None) -> dict:
    t0 = time.monotonic()
    started = model.utc_now()
    findings = []

    smi = probe.run(["nvidia-smi", "-q", "-x"])
    parsed, smi_fail = None, None
    if smi.ok:
        try:
            parsed = smi_xml.parse(smi.stdout)
        except smi_xml.SmiParseError as e:
            smi_fail = missing("error", smi_xml.SRC, "parse_failed", str(e), smi_xml.REF)
    else:
        smi_fail = cmd_failure_field(smi, smi_xml.SRC, smi_xml.REF)
    all_gpus = parsed["gpus"] if parsed else []

    if gpu_indices is not None:
        unknown = [i for i in gpu_indices if not 0 <= i < len(all_gpus)]
        if unknown:
            raise UnknownGpu(unknown, list(range(len(all_gpus))))

    nv = nvml_mod.collect(probe)

    # Learn every raw identifier first, so that no raw output can contain one.
    secrets = {}
    for g in all_gpus:
        secrets.update(ids.secrets_for(g["uuid"], g["serial"]))
    for dev in nv["devices"].values():
        secrets.update(ids.secrets_for(dev["uuid"], None))
    raws = model.RawStore(secrets)

    xml_text, redactions = ids.redact_smi_xml(smi.stdout) if smi.stdout else ("", [])
    raws.add_result("smi_q_x", smi, xml_text, redactions)

    topo_result = probe.run(["nvidia-smi", "topo", "-m"])
    raws.add_result("smi_topo_m", topo_result)

    klog = kernel_log.collect(probe)
    raws.add_result("kernel_log", klog.result, klog.text, kernel_log.REDACTIONS if klog.events is not None else ())

    raws.add("nvml_snapshot", "library", ["nvml"], json.dumps(nv["snapshot"], indent=1, sort_keys=True),
             status="ok" if nv["fail_field"] is None else nv["fail_field"]["status"])

    top = parsed["top"] if parsed else {k: dict(smi_fail) for k in _TOP_KEYS}
    host = host_mod.collect(probe, top, nv["version"], topo.field(topo_result), klog.field)

    gpus = [_build_gpu(i, g, nv, klog) for i, g in enumerate(all_gpus)
            if gpu_indices is None or i in gpu_indices]
    _check_duplicates(gpus, findings)
    if not all_gpus:
        findings.append({"code": "no_gpus", "severity": "warn", "path": None,
                         "detail": smi_fail["detail"] if smi_fail else None})

    return model.new_doc(
        mode=mode,
        started_at=started,
        finished_at=model.utc_now(),
        duration_s=round(time.monotonic() - t0, 3),
        utc_offset_s=probe.utc_offset_s(),
        provider=provider,
        options=options or {"gpus": gpu_indices, "load_minutes": None, "skip_dcgm": False, "submit": False},
        mock=probe.mock,
        fixture=probe.fixture,
        host=host,
        gpus=gpus,
        node={"gpu_count": len(all_gpus), "p2p_bandwidth": None, "verdict": None},
        findings=findings,
        raw=raws.entries,
    )


def _build_gpu(index: int, g: dict, nv: dict, klog) -> dict:
    m = gpumodels.identify(g["identity"]["name"]["value"])
    if m:
        model_key, form_factor = ok(m.key, "derived"), ok(m.form_factor, "derived")
    else:
        model_key = missing("not_supported", "derived", "unknown_model", g["identity"]["name"]["value"])
        form_factor = dict(model_key)
    identity = {"name": g["identity"]["name"], "model_key": model_key, "form_factor": form_factor}
    identity.update({k: v for k, v in g["identity"].items() if k != "name"})

    gpu = {
        "index": index,
        "pci_bus_id": g["bus_id"],
        "card": {"hash_scheme": ids.HASH_SCHEME, **g["card"]},
        "identity": identity,
        "history": g["history"],
        "snapshot": g["snapshot"],
        "findings": [],
        "diag": None,
        "perf": None,
        "load": None,
        "verdict": None,
    }
    _merge_nvml(gpu, nv["devices"].get(g["bus_id"]), nv)
    gpu["history"]["xid_events"] = kernel_log.events_field(klog, g["bus_id"])
    _apply_model_expectations(gpu, m)
    _check_power_limit(gpu)
    return gpu


def _merge_nvml(gpu: dict, dev: dict | None, nv: dict) -> None:
    """Use NVML where nvidia-smi gave no value. Record a finding where they disagree."""
    if dev is None:
        fail = nv["fail_field"] or missing("error", nvml_mod.SRC, "gpu_not_in_nvml", None, nvml_mod.REF)
        gpu["identity"]["nvlink"] = dict(fail)
        return
    for path, nf in dev["fields"].items():
        if path == "identity.nvlink":
            gpu["identity"]["nvlink"] = nf
            continue
        cur = model.get_path(gpu, path)
        if cur["status"] != "ok" and nf["status"] == "ok":
            model.set_path(gpu, path, dict(nf, reason="from_nvml", detail=f"nvidia-smi: {cur['reason']}"))
        elif cur["status"] == "ok" and nf["status"] == "ok" and cur["value"] != nf["value"]:
            gpu["findings"].append({"code": "smi_nvml_mismatch", "severity": "warn", "path": path,
                                    "detail": f"nvidia-smi={cur['value']} nvml={nf['value']}"})


def _apply_model_expectations(gpu: dict, m) -> None:
    """Turn 'N/A' into 'blocked' where the model is known to record the value."""
    if m is None:
        return
    hist = gpu["history"]
    ecc_off = hist["ecc_mode"]["status"] == "ok" and hist["ecc_mode"]["value"] is False
    expected = [("ecc_mode", hist["ecc_mode"]), ("ecc_mode_pending", hist["ecc_mode_pending"])]
    if m.has_ecc:
        expected += list(iter_fields(hist["ecc"]))
    if m.has_row_remap:
        expected += list(iter_fields(hist["row_remap"]))
    for path, f in expected:
        if f["status"] == "ok":
            continue
        if ecc_off and not path.startswith("ecc_mode"):
            f.update(status="not_supported", reason="ecc_disabled")
        elif f["reason"] in _HIDDEN_REASONS:
            f.update(status="blocked", reason="hidden_on_supported_model")
    if m.has_row_remap:
        for _, f in iter_fields(hist["retired_pages"]):
            if f["status"] != "ok" and f["reason"] in _HIDDEN_REASONS:
                f.update(status="not_supported", reason="replaced_by_row_remap")


def _check_power_limit(gpu: dict) -> None:
    """A power limit below the default makes the GPU slower. Providers can set it."""
    cur, default = gpu["identity"]["power_limit_current_w"], gpu["identity"]["power_limit_default_w"]
    if cur["status"] == "ok" and default["status"] == "ok" and cur["value"] < 0.95 * default["value"]:
        gpu["findings"].append({"code": "power_limit_below_default", "severity": "warn",
                                "path": "identity.power_limit_current_w",
                                "detail": f"{cur['value']:g} W of {default['value']:g} W"})


def _check_duplicates(gpus: list, findings: list) -> None:
    seen = {}
    for gpu in gpus:
        f = gpu["card"]["uuid_sha256"]
        if f["status"] != "ok":
            continue
        if f["value"] in seen:
            findings.append({"code": "duplicate_card_id", "severity": "warn", "path": None,
                             "detail": f"GPU {seen[f['value']]} and GPU {gpu['index']}"})
        seen.setdefault(f["value"], gpu["index"])
