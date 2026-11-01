"""Performance tests and the sustained load test.

TorchBench (torchbench.py) runs on real GPUs. MockBench (mockbench.py) gives
fixture values in mock mode. run_all() fills the result document from either.
"""
from __future__ import annotations

import statistics

from .. import model
from ..model import missing, ok

# NVML clock event (throttle) reason bits.
REASON_POWER_CAP = 0x4
REASON_HW_SLOWDOWN = 0x8
REASON_SW_THERMAL = 0x20
REASON_HW_THERMAL = 0x40
REASON_HW_POWER_BRAKE = 0x80
HW_SLOWDOWN_MASK = REASON_HW_SLOWDOWN | REASON_SW_THERMAL | REASON_HW_THERMAL | REASON_HW_POWER_BRAKE
WARMUP_S = 30  # Load samples before this time do not count for sustained performance.
REF = "perf_log"


class NotSupported(Exception):
    """This GPU or this PyTorch cannot do the test."""


def _measure(fn, log: dict, key: str) -> dict:
    try:
        value, detail = fn()
        log[key] = detail
        return ok(round(float(value), 1), "torch", REF)
    except NotSupported as e:
        log[key] = {"not_supported": str(e)}
        return missing("not_supported", "torch", "bench_not_supported", str(e), REF)
    except Exception as e:  # A failed test is a finding, not a crash.
        log[key] = {"error": f"{type(e).__name__}: {e}"}
        return missing("error", "torch", "bench_failed", f"{type(e).__name__}: {e}", REF)


def summarize_load(load: dict | None, failure: dict | None) -> dict:
    """Values for grading from a load series."""
    if load is None:
        f = failure or missing("skipped", "derived", "load_not_run", None, "load")
        return {k: dict(f) for k in ("sustained_bf16_tflops", "throttle_hw_fraction", "power_capped_fraction", "max_temp_c")}
    s = load["series"]
    n = len(s["t_s"])
    tflops = [v for t, v in zip(s["t_s"], s["tflops"]) if t >= WARMUP_S] or s["tflops"]
    masks = s["throttle_mask"]
    return {
        "sustained_bf16_tflops": ok(round(statistics.median(tflops), 1), "derived", "load"),
        "throttle_hw_fraction": ok(round(sum(1 for m in masks if m & HW_SLOWDOWN_MASK) / n, 4), "derived", "load"),
        "power_capped_fraction": ok(round(sum(1 for m in masks if m & REASON_POWER_CAP) / n, 4), "derived", "load"),
        "max_temp_c": ok(max(s["temp_c"]), "derived", "load"),
    }


def run_all(bench, doc: dict, minutes: int, say) -> dict:
    """Run every test on every GPU in doc. Fill gpu.perf, gpu.load and node.p2p_bandwidth. Return the log."""
    from .. import text as T

    log = {"started_at": model.utc_now(), "minutes": minutes, "gpus": {}, "p2p": None}
    indices = [g["index"] for g in doc["gpus"]]
    for gpu in doc["gpus"]:
        i = gpu["index"]
        say(T.PERF_GPU.format(index=i))
        glog = log["gpus"].setdefault(str(i), {})
        gpu["perf"] = {
            "bf16_tflops": _measure(lambda: bench.bf16_tflops(i), glog, "bf16"),
            "fp8_tflops": _measure(lambda: bench.fp8_tflops(i), glog, "fp8"),
            "hbm_gbps": _measure(lambda: bench.hbm_gbps(i), glog, "hbm"),
        }

    if len(indices) > 1:
        say(T.PERF_P2P)
        p2p_log: dict = {}
        try:
            pairs = bench.p2p(indices)
            doc["node"]["p2p_bandwidth"] = ok({"pairs": pairs}, "torch", REF)
            p2p_log["pairs"] = pairs
        except Exception as e:
            doc["node"]["p2p_bandwidth"] = missing("error", "torch", "bench_failed", f"{type(e).__name__}: {e}", REF)
            p2p_log["error"] = str(e)
        log["p2p"] = p2p_log
    else:
        doc["node"]["p2p_bandwidth"] = missing("not_supported", "torch", "single_gpu", None, None)

    say(T.LOAD_START.format(minutes=minutes, count=len(indices)))
    loads, errors = bench.load(indices, minutes)
    for gpu in doc["gpus"]:
        i = gpu["index"]
        load = loads.get(i)
        failure = None
        if load is None:
            failure = missing("error", "torch", "bench_failed", errors.get(i, "no load data"), REF)
        gpu["load"] = load
        gpu["perf"].update(summarize_load(load, failure))
    log["finished_at"] = model.utc_now()
    log["load_errors"] = {str(k): v for k, v in errors.items()}
    return log


def skip_all(doc: dict, reason: str, detail: str | None = None) -> None:
    """Mark every performance value as not measured."""
    f = missing("skipped", "torch", reason, detail, None)
    for gpu in doc["gpus"]:
        gpu["perf"] = {k: dict(f) for k in ("bf16_tflops", "fp8_tflops", "hbm_gbps", "sustained_bf16_tflops",
                                            "throttle_hw_fraction", "power_capped_fraction", "max_temp_c")}
        gpu["load"] = None
    doc["node"]["p2p_bandwidth"] = dict(f)
