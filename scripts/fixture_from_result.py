"""Make a mock-mode fixture from a real full-test result file.

The raw output in the result file is already redacted, so the fixture has no
raw UUIDs or serial numbers. Values that dud reads without a raw entry (the OS
name, the CPU model, the container type) come from the parsed values.

Run:
  .venv/bin/python scripts/fixture_from_result.py <result.json> <fixture name> "<one-line description>"
"""
from __future__ import annotations

import base64
import gzip
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {"smi_q_x": "nvidia-smi-q-x.xml", "smi_topo_m": "nvidia-smi-topo-m.txt", "dcgm_diag": "dcgm-diag.json"}


def text(entry: dict) -> str:
    return gzip.decompress(base64.b64decode(entry["content"])).decode("utf-8")


def value(field):
    return field["value"] if isinstance(field, dict) and field.get("status") == "ok" else None


def load_spec(load: dict) -> dict:
    """Mock-bench parameters that reproduce the real load series."""
    s = load["series"]
    n = len(s["t_s"])
    throttle = []
    for bit in range(16):
        mask = 1 << bit
        frac = sum(1 for m in s["throttle_mask"] if m & mask) / n
        if frac > 0:
            throttle.append({"mask": mask, "fraction": round(frac, 3)})
    return {
        "sm_clock": int(statistics.median(s["sm_clock_mhz"])),
        "mem_clock": int(statistics.median(s["mem_clock_mhz"])),
        "temp_start": s["temp_c"][0],
        "temp_end": max(s["temp_c"]),
        "power": round(statistics.median(s["power_w"]), 1),
        "power_jitter": round(max(1.0, statistics.pstdev(s["power_w"])), 1),
        # The mean, not the median: dud 0.2.0 counted work in steps of 16 multiplies.
        "tflops": round(statistics.fmean(s["tflops"]), 1),
        "throttle": throttle,
    }


def main(result_path: str, name: str, description: str) -> None:
    doc = json.loads(Path(result_path).read_text())
    out = ROOT / "fixtures" / name
    out.mkdir(parents=True, exist_ok=True)
    raw = {r["id"]: r for r in doc["raw"]}
    commands = {}
    for rid, entry in raw.items():
        if entry["kind"] != "command" or rid.endswith("_after"):
            continue
        item = {"exit_code": entry["exit_code"]}
        if entry.get("stderr"):
            item["stderr"] = entry["stderr"] + "\n"
        body = text(entry)
        if rid in FILES:
            (out / FILES[rid]).write_text(body)
            item["stdout_file"] = FILES[rid]
        elif body:
            item["stdout"] = body
        commands[" ".join(entry["command"])] = item

    host = doc["host"]
    env = host["environment"]
    # The kernel log detail lists each failed attempt as "<command>: <error>".
    for part in (host["kernel_log"].get("detail") or "").split("; "):
        if part.startswith("journalctl: "):
            commands["journalctl -k --no-pager -o short-monotonic"] = {"exit_code": 1, "stderr": part[12:] + "\n"}
    if value(host["kernel"]):
        commands["uname -r"] = {"exit_code": 0, "stdout": value(host["kernel"]) + "\n"}
    if value(env["virtualization"]):
        commands["systemd-detect-virt"] = {"exit_code": 0, "stdout": value(env["virtualization"]) + "\n"}

    files = {}
    if value(host["os"]):
        files["/etc/os-release"] = {"text": f'PRETTY_NAME="{value(host["os"])}"\n'}
    if value(host["cpu_model"]):
        files["/proc/cpuinfo"] = {"text": f"model name\t: {value(host['cpu_model'])}\nflags\t\t: fpu vme de pse\n"}
    for key, path in (("dmi_vendor", "/sys/class/dmi/id/sys_vendor"), ("dmi_product", "/sys/class/dmi/id/product_name")):
        if value(env[key]):
            files[path] = {"text": value(env[key]) + "\n"}
    paths = ["/.dockerenv"] if value(env["container"]) == "docker" else []

    nvml = json.loads(text(raw["nvml_snapshot"])) if "nvml_snapshot" in raw else None
    if nvml is not None:
        (out / "nvml.json").write_text(json.dumps(nvml, indent=2) + "\n")

    bench = {"gpus": {}}
    for g in doc["gpus"]:
        perf = g.get("perf") or {}
        entry = {k: value(perf.get(k)) for k in ("bf16_tflops", "fp8_tflops", "hbm_gbps")}
        for k in ("fp8_tflops", "bf16_tflops", "hbm_gbps"):
            if entry[k] is None and perf.get(k):
                entry[f"{k}_note"] = perf[k].get("detail") or perf[k].get("reason")
        if g.get("load"):
            entry["load"] = load_spec(g["load"])
        bench["gpus"][str(g["index"])] = entry
    (out / "bench.json").write_text(json.dumps(bench, indent=2) + "\n")

    spec = {
        "description": description,
        "synthetic": False,
        "source_run": doc["run"]["run_id"],
        "commands": commands,
        "files": files,
        "paths": paths,
        "euid": 0 if value(env["is_root"]) else 1000,
        "utc_offset_s": doc["run"]["utc_offset_s"] or 0,
        "bench_file": "bench.json",
    }
    if nvml is not None:
        spec["nvml_file"] = "nvml.json"
    (out / "fixture.json").write_text(json.dumps(spec, indent=2) + "\n")
    print(f"Wrote fixtures/{name}/")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
