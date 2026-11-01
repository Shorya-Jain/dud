"""Mock performance tests: values from the fixture file bench.json.

The load series is made at once from the fixture values with a fixed random
seed. It looks like a real series (temperature rises, power moves), so the
registry's physical checks accept it.
"""
from __future__ import annotations

import math
import random

from . import NotSupported


class MockBench:
    def __init__(self, data: dict, fixture: str):
        self.data = data
        self.fixture = fixture

    def _gpu(self, i: int) -> dict:
        return self.data.get("gpus", {}).get(str(i), self.data.get("default", {}))

    def _value(self, i: int, key: str):
        v = self._gpu(i).get(key)
        if v is None:
            raise NotSupported(self._gpu(i).get(f"{key}_note", "not supported on this GPU"))
        if isinstance(v, dict) and "error" in v:
            raise RuntimeError(v["error"])
        return v, {"mock": True}

    def bf16_tflops(self, i: int):
        return self._value(i, "bf16_tflops")

    def fp8_tflops(self, i: int):
        return self._value(i, "fp8_tflops")

    def hbm_gbps(self, i: int):
        return self._value(i, "hbm_gbps")

    def p2p(self, indices: list) -> list:
        p = self.data.get("p2p")
        if not p:
            raise RuntimeError("no GPU-to-GPU data in the fixture")
        rng = random.Random(f"{self.fixture}-p2p")
        return [{"src": s, "dst": d, "gbps": round(p["gbps"] * rng.uniform(0.97, 1.03), 1), "peer_access": p["peer_access"]}
                for s in indices for d in indices if s != d]

    def load(self, indices: list, minutes: int) -> tuple:
        loads, errors = {}, {}
        for i in indices:
            spec = self._gpu(i).get("load")
            if spec is None:
                errors[i] = "the fixture has no load data for this GPU"
                continue
            loads[i] = make_series(spec, minutes, random.Random(f"{self.fixture}-load-{i}"))
        return loads, errors


def make_series(spec: dict, minutes: int, rng: random.Random) -> dict:
    n = minutes * 60
    s = {k: [] for k in ("t_s", "sm_clock_mhz", "mem_clock_mhz", "temp_c", "power_w", "util_pct", "throttle_mask", "tflops")}
    temp = float(spec["temp_start"])
    for t in range(1, n + 1):
        target = spec["temp_end"] - (spec["temp_end"] - spec["temp_start"]) * math.exp(-t / 150)
        temp += (target - temp) * 0.5 + rng.gauss(0, 0.25)
        mask = 0
        for th in spec.get("throttle", []):
            if t > th.get("after_s", 0) and rng.random() < th["fraction"]:
                mask |= th["mask"]
        slow = mask & 0xE8
        clock = spec["sm_clock"] - (rng.choice([0, 15, 30]) if mask & 0x4 else 0) - (spec.get("slow_clock_drop", 300) if slow else 0)
        s["t_s"].append(float(t))
        s["sm_clock_mhz"].append(int(clock))
        s["mem_clock_mhz"].append(int(spec["mem_clock"]))
        s["temp_c"].append(int(round(temp)))
        s["power_w"].append(round(spec["power"] + rng.gauss(0, spec["power_jitter"]), 1))
        s["util_pct"].append(100 if rng.random() > 0.05 else 99)
        s["throttle_mask"].append(mask)
        s["tflops"].append(round(spec["tflops"] * (0.82 if slow else 1.0) * rng.uniform(0.985, 1.015), 1))
    return {"interval_s": 1, "minutes": minutes, "series": s}
