"""Performance tests on real GPUs with PyTorch, and NVML samples during the load test.

Import this module only after fulltest has set CUDA_DEVICE_ORDER=PCI_BUS_ID, so
that CUDA GPU numbers are the same as nvidia-smi and NVML numbers.
"""
from __future__ import annotations

import statistics
import threading
import time

from . import NotSupported

N = 8192  # Matrix size for BF16 and FP8 tests.


class NvmlSampler:
    """One sample of each GPU: clocks, temperature, power, utilization and throttle reasons."""

    def __init__(self, indices: list):
        import pynvml

        self.n = pynvml
        pynvml.nvmlInit()
        self.handles = {i: pynvml.nvmlDeviceGetHandleByIndex(i) for i in indices}
        self._reasons = getattr(pynvml, "nvmlDeviceGetCurrentClocksEventReasons", None) or \
            getattr(pynvml, "nvmlDeviceGetCurrentClocksThrottleReasons")

    def sample(self, i: int) -> dict:
        n, h = self.n, self.handles[i]
        return {
            "sm_clock_mhz": n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_SM),
            "mem_clock_mhz": n.nvmlDeviceGetClockInfo(h, n.NVML_CLOCK_MEM),
            "temp_c": n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU),
            "power_w": round(n.nvmlDeviceGetPowerUsage(h) / 1000.0, 1),
            "util_pct": n.nvmlDeviceGetUtilizationRates(h).gpu,
            "throttle_mask": int(self._reasons(h)),
        }

    def close(self):
        try:
            self.n.nvmlShutdown()
        except Exception:
            pass


class TorchBench:
    def __init__(self):
        import torch

        self.torch = torch

    def _dev(self, i: int):
        return self.torch.device(f"cuda:{i}")

    def _time(self, dev, fn, iters: int, warmup: int = 5) -> float:
        """Seconds for `iters` calls of fn, measured with CUDA events."""
        torch = self.torch
        with torch.cuda.device(dev):
            for _ in range(warmup):
                fn()
            torch.cuda.synchronize(dev)
            start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            start.record()
            for _ in range(iters):
                fn()
            end.record()
            end.synchronize()
            return start.elapsed_time(end) / 1000.0

    def bf16_tflops(self, i: int, iters: int = 50):
        torch, dev = self.torch, self._dev(i)
        a = torch.randn(N, N, device=dev, dtype=torch.bfloat16)
        b = torch.randn(N, N, device=dev, dtype=torch.bfloat16)
        c = torch.empty_like(a)
        s = self._time(dev, lambda: torch.matmul(a, b, out=c), iters)
        del a, b, c
        return 2 * N ** 3 * iters / s / 1e12, {"n": N, "iters": iters, "seconds": round(s, 4)}

    def fp8_tflops(self, i: int, iters: int = 50):
        torch, dev = self.torch, self._dev(i)
        if not hasattr(torch, "float8_e4m3fn") or not hasattr(torch, "_scaled_mm"):
            raise NotSupported("this PyTorch has no FP8 matrix multiply")
        major, minor = torch.cuda.get_device_capability(dev)
        if (major, minor) < (8, 9):
            raise NotSupported(f"compute capability {major}.{minor} has no FP8 tensor cores")
        a = torch.randn(N, N, device=dev).to(torch.float8_e4m3fn)
        b = torch.randn(N, N, device=dev).to(torch.float8_e4m3fn).t()  # The second matrix must be column-major.
        one = torch.tensor(1.0, device=dev)
        s = self._time(dev, lambda: torch._scaled_mm(a, b, scale_a=one, scale_b=one, out_dtype=torch.bfloat16), iters)
        del a, b
        return 2 * N ** 3 * iters / s / 1e12, {"n": N, "iters": iters, "seconds": round(s, 4)}

    def hbm_gbps(self, i: int, gib: int = 2, iters: int = 20):
        torch, dev = self.torch, self._dev(i)
        nbytes = gib * 2 ** 30
        x = torch.empty(nbytes // 4, device=dev, dtype=torch.float32)
        y = torch.empty_like(x)
        s = self._time(dev, lambda: y.copy_(x), iters)
        del x, y
        # A copy reads and writes each byte.
        return 2 * nbytes * iters / s / 1e9, {"bytes": nbytes, "iters": iters, "seconds": round(s, 4)}

    def p2p(self, indices: list, mib: int = 512, iters: int = 10) -> list:
        torch = self.torch
        nbytes = mib * 2 ** 20
        pairs = []
        for src in indices:
            for dst in indices:
                if src == dst:
                    continue
                x = torch.empty(nbytes // 4, device=self._dev(src), dtype=torch.float32)
                y = torch.empty_like(x, device=self._dev(dst))
                for _ in range(2):
                    y.copy_(x)
                torch.cuda.synchronize(self._dev(src))
                torch.cuda.synchronize(self._dev(dst))
                t0 = time.perf_counter()
                for _ in range(iters):
                    y.copy_(x, non_blocking=True)
                torch.cuda.synchronize(self._dev(src))
                torch.cuda.synchronize(self._dev(dst))
                s = time.perf_counter() - t0
                pairs.append({"src": src, "dst": dst, "gbps": round(nbytes * iters / s / 1e9, 1),
                              "peer_access": bool(torch.cuda.can_device_access_peer(src, dst))})
                del x, y
        return pairs

    def load(self, indices: list, minutes: int) -> tuple:
        """BF16 matrix multiplies on every GPU for `minutes`. One NVML sample each second."""
        torch = self.torch
        stop = threading.Event()
        counts = {i: 0 for i in indices}
        errors: dict = {}

        def work(i):
            try:
                dev = self._dev(i)
                with torch.cuda.device(dev):
                    a = torch.randn(N, N, device=dev, dtype=torch.bfloat16)
                    b = torch.randn(N, N, device=dev, dtype=torch.bfloat16)
                    c = torch.empty_like(a)
                    while not stop.is_set():
                        for _ in range(16):
                            torch.matmul(a, b, out=c)
                        torch.cuda.synchronize(dev)
                        counts[i] += 16
            except Exception as e:
                errors[i] = f"{type(e).__name__}: {e}"

        sampler = NvmlSampler(indices)
        series = {i: {k: [] for k in ("t_s", "sm_clock_mhz", "mem_clock_mhz", "temp_c", "power_w", "util_pct",
                                      "throttle_mask", "tflops")} for i in indices}
        threads = [threading.Thread(target=work, args=(i,), daemon=True) for i in indices]
        for t in threads:
            t.start()
        t0 = time.monotonic()
        last = {i: (t0, 0) for i in indices}
        try:
            for step in range(1, minutes * 60 + 1):
                time.sleep(max(0.0, t0 + step - time.monotonic()))
                now = time.monotonic()
                for i in indices:
                    if i in errors:
                        continue
                    s = sampler.sample(i)
                    done = counts[i]
                    prev_t, prev_n = last[i]
                    last[i] = (now, done)
                    tf = (done - prev_n) * 2 * N ** 3 / max(1e-6, now - prev_t) / 1e12
                    row = series[i]
                    row["t_s"].append(round(now - t0, 2))
                    row["tflops"].append(round(tf, 1))
                    for k, v in s.items():
                        row[k].append(v)
        finally:
            stop.set()
            for t in threads:
                t.join(timeout=60)
            sampler.close()
        loads = {}
        for i in indices:
            if i not in errors and series[i]["t_s"]:
                loads[i] = {"interval_s": 1, "minutes": minutes, "series": series[i],
                            "median_tflops": statistics.median(series[i]["tflops"])}
        return loads, errors
