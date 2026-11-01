"""DCGM diagnostic: `dcgmi diag -r 3 -j`.

The JSON format changes between DCGM versions, so the parser looks for any
object with a "name" and a list of "results", at any depth.
"""
from __future__ import annotations

import json

from ..model import missing, ok
from .common import cmd_failure_field

SRC = "dcgm"
REF = "dcgm_diag"
LEVEL = 3
TIMEOUT_S = 3600

_STATUS = {"pass": "pass", "fail": "fail", "warn": "warn", "warning": "warn",
           "skip": "skip", "skipped": "skip", "not run": "skip", "notrun": "skip"}


class DcgmParseError(ValueError):
    pass


def argv(gpu_indices: list | None) -> list:
    cmd = ["dcgmi", "diag", "-r", str(LEVEL), "-j"]
    if gpu_indices is not None:
        cmd += ["-i", ",".join(map(str, gpu_indices))]
    return cmd


def _ids(result: dict) -> list | None:
    for key in ("gpu_ids", "gpu_id", "entity_id", "gpu"):
        if key in result and result[key] is not None:
            raw = result[key]
            parts = raw if isinstance(raw, list) else str(raw).split(",")
            try:
                return [int(str(p).strip()) for p in parts if str(p).strip() != ""]
            except ValueError:
                return None
    return None


def _info(result: dict) -> str | None:
    texts = []
    for key in ("info", "warnings", "warning", "errors", "error"):
        v = result.get(key)
        items = v if isinstance(v, list) else [v] if v else []
        for item in items:
            texts.append(item.get("warning") or item.get("error") or json.dumps(item) if isinstance(item, dict) else str(item))
    return "; ".join(t for t in texts if t)[:400] or None


def parse(text: str) -> dict:
    """Return {version, tests: [{name, status, gpus (list or None for all), info}]}."""
    start = text.find("{")
    if start < 0:
        raise DcgmParseError("no JSON in the output")
    try:
        data = json.loads(text[start:])
    except ValueError as e:
        raise DcgmParseError(str(e))
    tests = []

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("name"), str) and isinstance(o.get("results"), list):
                for r in o["results"]:
                    if isinstance(r, dict):
                        status = _STATUS.get(str(r.get("status", "")).strip().lower(), "unknown")
                        tests.append({"name": o["name"], "status": status, "gpus": _ids(r), "info": _info(r)})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    if not tests:
        raise DcgmParseError("no test results in the output")
    version = data.get("version") if isinstance(data, dict) else None
    return {"version": str(version) if version else None, "tests": tests}


def per_gpu(parsed: dict, index: int) -> dict:
    """Tests that apply to one GPU, and its overall result: fail, warn or pass."""
    tests = [{"name": t["name"], "result": t["status"], "info": t["info"]}
             for t in parsed["tests"] if t["gpus"] is None or index in t["gpus"]]
    statuses = {t["result"] for t in tests}
    result = "fail" if "fail" in statuses else "warn" if "warn" in statuses else "pass"
    return {"level": LEVEL, "version": parsed["version"], "result": result, "tests": tests}


def run(probe, gpu_indices: list | None) -> tuple:
    """Run the diagnostic. Returns (CmdResult, parsed or None, failure Field or None)."""
    cmd = argv(gpu_indices)
    result = probe.run(cmd, timeout=TIMEOUT_S)
    if not result.ok and "connect" in (result.stderr + result.stdout).lower():
        # The DCGM host engine does not run. Start it and try again.
        if probe.run(["nv-hostengine"], timeout=60).ok:
            result = probe.run(cmd, timeout=TIMEOUT_S)
    if result.failure == "not_found":
        return result, None, missing("skipped", SRC, "dcgm_not_installed", None, REF)
    try:
        # dcgmi exits with a non-zero code when a test fails, but the JSON is complete.
        return result, parse(result.stdout), None
    except DcgmParseError as e:
        if not result.ok:
            return result, None, cmd_failure_field(result, SRC, REF)
        return result, None, missing("error", SRC, "parse_failed", str(e), REF)


def fields(parsed: dict | None, failure: dict | None, index: int) -> dict:
    if parsed is None:
        return {"dcgm_result": dict(failure), "dcgm": dict(failure)}
    g = per_gpu(parsed, index)
    return {"dcgm_result": ok(g["result"], SRC, REF), "dcgm": ok(g, SRC, REF)}


def skipped(reason: str) -> dict:
    f = missing("skipped", SRC, reason, None, None)
    return {"dcgm_result": f, "dcgm": dict(f)}
