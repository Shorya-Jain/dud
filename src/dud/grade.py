"""Verdicts: KEEP, KILL or UNKNOWN, from the rules in grading.yaml.

The registry has the same engine in server/src/grade.ts and uses a JSON copy of
grading.yaml. tests/test_grade.py and server/test/units.test.ts keep them the same.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import model
from . import text as T

ROOT = Path(__file__).resolve().parents[2]
_PACKAGED = Path(__file__).resolve().parent / "rules"


def _load_yaml_or_json(name: str) -> dict:
    """Load <name>.yaml from the repository, or the packaged JSON copy."""
    src = ROOT / f"{name}.yaml"
    if src.is_file():
        try:
            import yaml

            return yaml.safe_load(src.read_text())
        except ImportError:
            pass
    return json.loads((_PACKAGED / f"{name}.json").read_text())


_cache: dict = {}


def rules() -> dict:
    if "grading" not in _cache:
        _cache["grading"] = _load_yaml_or_json("grading")
    return _cache["grading"]


def specs() -> dict:
    if "specs" not in _cache:
        _cache["specs"] = _load_yaml_or_json("specs")
    return _cache["specs"]


def spec_value(model_key: str | None, key: str):
    item = specs()["models"].get(model_key or "", {}).get(key)
    return item.get("value") if isinstance(item, dict) else None


def _pct(x) -> str:
    return f"{x * 100:.0f} %"


def _num(x) -> str:
    if isinstance(x, float):
        return f"{x:.1f}" if abs(x) < 100 else f"{x:.0f}"
    return str(x)


def evaluate_rule(rule: dict, gpu: dict) -> dict:
    """Return {rule, result, value, limit, verdict, text}. result: pass, fail, missing."""
    check = rule["check"]
    f = model.get_path(gpu, rule["value"])
    value = f["value"] if model.is_field(f) and f["status"] == "ok" else None
    limit = None
    spec_v = None
    ok = None
    if value is not None:
        if "max" in check:
            limit = check["max"]
            ok = value <= limit
        elif "is" in check:
            limit = check["is"]
            ok = value == limit
        elif "not_in" in check:
            limit = check["not_in"]
            ok = value not in limit
        elif "min_spec_fraction" in check:
            limit = check["min_spec_fraction"]
            spec_v = spec_value(gpu["identity"]["model_key"]["value"], check["spec"])
            if spec_v:
                ok = value >= limit * spec_v
            else:
                value = None  # No datasheet value: the rule cannot judge.
        else:
            raise ValueError(f"unknown check in rule {rule['id']}")
    result = "missing" if ok is None else ("pass" if ok else "fail")
    fraction = (value / spec_v) if (spec_v and value is not None) else value
    template = rule["explain"][result]
    text = template.format(
        value=_num(value) if value is not None else "-",
        limit=_num(limit) if not isinstance(limit, list) else ", ".join(map(str, limit)),
        value_pct=_pct(fraction) if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) else "-",
        limit_pct=_pct(limit) if isinstance(limit, (int, float)) and not isinstance(limit, bool) else "-",
        spec_value=_num(spec_v) if spec_v else "-",
    )
    return {"rule": rule["id"], "result": result, "value": value, "limit": limit,
            "verdict": rule["verdict"] if result == "fail" else None, "text": text}


def grade_gpu(gpu: dict, mode: str) -> dict:
    results, verdict = [], "KEEP"
    for rule in rules()["rules"]:
        if mode not in rule["modes"]:
            continue
        r = evaluate_rule(rule, gpu)
        if r["result"] == "missing" and rule["if_missing"] == "skip":
            r["result"] = "skipped"
        results.append(r)
        if r["result"] == "fail" and rule["verdict"] == "KILL":
            verdict = "KILL"
        elif r["result"] == "missing" and verdict != "KILL":
            verdict = "UNKNOWN"
    lines = [r["text"] for r in results if r["result"] == "fail"] or \
            [r["text"] for r in results if r["result"] == "missing"]
    summary = " ".join(lines) if lines else T.VERDICT_ALL_PASSED
    return {"verdict": verdict, "local_verdict": verdict, "rules_version": rules()["version"],
            "results": results, "registry": None, "summary": summary}


def grade_node(gpus: list) -> dict:
    verdicts = [g["verdict"]["verdict"] for g in gpus if g.get("verdict")]
    if not verdicts:
        node = "UNKNOWN"
    elif "KILL" in verdicts:
        node = "KILL"
    elif "UNKNOWN" in verdicts:
        node = "UNKNOWN"
    else:
        node = "KEEP"
    bad = [str(g["index"]) for g in gpus if g.get("verdict") and g["verdict"]["verdict"] == node]
    summary = {"KEEP": T.NODE_KEEP, "KILL": T.NODE_KILL, "UNKNOWN": T.NODE_UNKNOWN}[node].format(gpus=", ".join(bad))
    return {"verdict": node, "summary": summary,
            "gpus": [{"index": g["index"], "verdict": g["verdict"]["verdict"]} for g in gpus if g.get("verdict")]}


def grade_doc(doc: dict) -> None:
    """Grade every GPU and the node. For a quick test, also use the registry readings."""
    mode = doc["run"]["mode"]
    for gpu in doc["gpus"]:
        gpu["verdict"] = grade_gpu(gpu, mode)
        if mode == "quick":
            _use_registry(doc, gpu)
    doc["node"]["verdict"] = grade_node(doc["gpus"])


def _days_ago(date: str, now: datetime) -> int:
    d = datetime.strptime(date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return max(0, (now - d).days)


def _use_registry(doc: dict, gpu: dict) -> None:
    """Combine the local verdict with the newest registry verdict of the card."""
    reg = doc.get("registry") or {}
    data = reg.get("cards", {}).get(gpu["card"]["uuid_sha256"]["value"] or "")
    v = gpu["verdict"]
    graded = [r for r in (data or {}).get("readings", []) if r.get("verdict") in ("KEEP", "KILL", "UNKNOWN")]
    if not graded:
        if data is not None:
            v["registry"] = {"date": None, "verdict": None, "days_ago": None}
        return
    newest = graded[-1]
    kills = [r for r in graded if r["verdict"] == "KILL"]
    now = datetime.now(timezone.utc)
    days = _days_ago(newest["date"], now)
    v["registry"] = {"date": newest["date"], "verdict": newest["verdict"], "days_ago": days,
                     "kill_since": kills[0]["date"] if kills else None}
    if v["local_verdict"] == "KILL":
        return
    if kills:
        v["verdict"] = "KILL"
        v["summary"] = T.REGISTRY_KILL.format(date=kills[0]["date"]) + " " + v["summary"]
    elif newest["verdict"] == "KEEP" and days <= rules()["registry_recent_days"]:
        when = T.WHEN_TODAY if days == 0 else T.WHEN_ONE_DAY if days == 1 else T.WHEN_DAYS.format(days=days)
        if v["local_verdict"] != "KEEP":
            v["summary"] = v["summary"] + " " + T.REGISTRY_KEEP_BUT_UNKNOWN.format(when=when)
        elif _counts_went_up(gpu, newest):
            v["summary"] = T.REGISTRY_KEEP_COUNTS_UP.format(when=when)
        else:
            v["summary"] = T.REGISTRY_RECENT_KEEP.format(when=when)


# Aggregate counters now, compared with the same counters in the newest registry reading.
_COUNTS = [("history.ecc.aggregate.correctable", "ecc", "aggregate_correctable"),
           ("history.ecc.aggregate.uncorrectable", "ecc", "aggregate_uncorrectable"),
           ("history.row_remap.correctable", "row_remap", "correctable"),
           ("history.row_remap.uncorrectable", "row_remap", "uncorrectable")]


def _counts_went_up(gpu: dict, reading: dict) -> bool:
    for path, group, key in _COUNTS:
        now = model.get_path(gpu, path)
        before = (reading.get(group) or {}).get(key)
        if model.is_field(now) and now["status"] == "ok" and before is not None and now["value"] > before:
            return True
    return False
