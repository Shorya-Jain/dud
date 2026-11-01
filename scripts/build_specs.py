#!/usr/bin/env python3
"""Check specs.yaml and grading.yaml, and write their JSON copies.

The JSON copies go to:
- server/src/      for the registry,
- src/dud/rules/   for installed copies of dud (the YAML files are not in the package).

Run: .venv/bin/python scripts/build_specs.py
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUTS = [ROOT / "server" / "src", ROOT / "src" / "dud" / "rules"]
sys.path.insert(0, str(ROOT / "src"))

from dud.gpumodels import _MODELS  # noqa: E402

CHECKS = {"max", "is", "not_in", "min_spec_fraction"}


def check_specs(specs: dict) -> list:
    errors = []
    known = {m.key for _, m in _MODELS}
    for key, model in specs["models"].items():
        if key not in known:
            errors.append(f"{key}: not in src/dud/gpumodels.py")
        for name, item in model.items():
            if name == "name":
                continue
            if not isinstance(item, dict) or "source" not in item:
                errors.append(f"{key}.{name}: no source")
            elif "value" not in item and not ("min" in item and "max" in item):
                errors.append(f"{key}.{name}: no value and no min/max")
        for need in ("memory_mib", "power_default_w", "fp16_dense_tflops"):
            if need not in model:
                errors.append(f"{key}: no {need}")
    for key in known - set(specs["models"]):
        errors.append(f"{key}: in gpumodels.py but not in specs.yaml")
    return errors


def check_grading(grading: dict, specs: dict) -> list:
    errors = []
    ids = set()
    spec_keys = {k for m in specs["models"].values() for k in m}
    for rule in grading["rules"]:
        rid = rule.get("id", "?")
        if rid in ids:
            errors.append(f"rule {rid}: the id repeats")
        ids.add(rid)
        if len(set(rule.get("check", {})) & CHECKS) != 1:
            errors.append(f"rule {rid}: check must have one of {sorted(CHECKS)}")
        if "min_spec_fraction" in rule.get("check", {}) and rule["check"].get("spec") not in spec_keys:
            errors.append(f"rule {rid}: spec {rule['check'].get('spec')} is not in specs.yaml")
        if rule.get("verdict") != "KILL":
            errors.append(f"rule {rid}: verdict must be KILL")
        if rule.get("if_missing") not in ("unknown", "skip"):
            errors.append(f"rule {rid}: if_missing must be unknown or skip")
        if not set(rule.get("modes", [])) <= {"quick", "full"} or not rule.get("modes"):
            errors.append(f"rule {rid}: modes must be quick and/or full")
        explain = rule.get("explain", {})
        for key in ("pass", "fail", "missing"):
            if key not in explain:
                errors.append(f"rule {rid}: explain.{key} is missing")
            for name in re.findall(r"\{(\w+)\}", explain.get(key, "")):
                if name not in ("value", "limit", "value_pct", "limit_pct", "spec_value"):
                    errors.append(f"rule {rid}: unknown placeholder {{{name}}}")
    return errors


def main() -> int:
    specs = yaml.safe_load((ROOT / "specs.yaml").read_text())
    grading = yaml.safe_load((ROOT / "grading.yaml").read_text())
    errors = check_specs(specs) + check_grading(grading, specs)
    if errors:
        print("\n".join(errors))
        return 1
    flagged = [f"{k}.{n}" for k, m in specs["models"].items() for n, v in m.items()
               if isinstance(v, dict) and v.get("verify")]
    for out in OUTS:
        out.mkdir(parents=True, exist_ok=True)
        (out / "specs.json").write_text(json.dumps({"challenge": specs["challenge"], "models": specs["models"]}, indent=1) + "\n")
        (out / "grading.json").write_text(json.dumps(grading, indent=1) + "\n")
    print(f"Wrote specs.json and grading.json to {len(OUTS)} folders. {len(flagged)} values have verify: true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
