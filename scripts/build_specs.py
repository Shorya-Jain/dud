#!/usr/bin/env python3
"""Check specs.yaml and write the JSON copy that the registry server uses.

Run: .venv/bin/python scripts/build_specs.py
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "server" / "src" / "specs.json"
sys.path.insert(0, str(ROOT / "src"))

from dud.gpumodels import _MODELS  # noqa: E402


def check(specs: dict) -> list:
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


def main() -> int:
    specs = yaml.safe_load((ROOT / "specs.yaml").read_text())
    errors = check(specs)
    if errors:
        print("\n".join(errors))
        return 1
    flagged = [f"{k}.{n}" for k, m in specs["models"].items() for n, v in m.items()
               if isinstance(v, dict) and v.get("verify")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"challenge": specs["challenge"], "models": specs["models"]}, indent=1) + "\n")
    print(f"Wrote {OUT.relative_to(ROOT)}. {len(flagged)} values have verify: true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
