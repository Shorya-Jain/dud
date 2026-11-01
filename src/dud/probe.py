"""Access to the machine: commands, files, environment and NVML.

All collection goes through a Probe. RealProbe reads the real machine.
MockProbe (DUD_MOCK=1) reads a fixture folder, so dud runs without a GPU.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .model import DudError, utc_now

REPO_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
DEFAULT_FIXTURE = "h100_sxm_healthy"


@dataclass
class CmdResult:
    argv: list
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    started_at: str = ""
    duration_ms: int = 0
    # None when the command worked. Else: not_found, permission, timeout or exit_code.
    failure: str | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


def classify_failure(stderr: str) -> str:
    low = (stderr or "").lower()
    if "operation not permitted" in low or "permission denied" in low or "insufficient permissions" in low:
        return "permission"
    return "exit_code"


class NvmlFail(Exception):
    """kind is one of: missing, not_supported, no_permission, error."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


# --- Real machine ------------------------------------------------------------

def _text(value) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


class RealNvml:
    def __init__(self):
        try:
            import pynvml
        except ImportError:
            raise NvmlFail("missing", "nvidia-ml-py is not installed")
        self._n = pynvml
        self._call(pynvml.nvmlInit)

    def _call(self, fn, *args):
        n = self._n
        try:
            return fn(*args)
        except n.NVMLError as e:
            kind = {
                n.NVML_ERROR_NOT_SUPPORTED: "not_supported",
                n.NVML_ERROR_NO_PERMISSION: "no_permission",
                n.NVML_ERROR_LIBRARY_NOT_FOUND: "missing",
                n.NVML_ERROR_DRIVER_NOT_LOADED: "missing",
            }.get(getattr(e, "value", None), "error")
            raise NvmlFail(kind, str(e))

    def version(self) -> str:
        return _text(self._call(self._n.nvmlSystemGetNVMLVersion))

    def count(self) -> int:
        return int(self._call(self._n.nvmlDeviceGetCount))

    def get(self, index: int, key: str):
        n = self._n
        h = self._call(n.nvmlDeviceGetHandleByIndex, index)
        if key == "uuid":
            return _text(self._call(n.nvmlDeviceGetUUID, h))
        if key == "pci_bus_id":
            return _text(self._call(n.nvmlDeviceGetPciInfo, h).busId)
        if key == "memory_total_bytes":
            return int(self._call(n.nvmlDeviceGetMemoryInfo, h).total)
        if key == "remapped_rows":
            corr, unc, pending, failed = self._call(n.nvmlDeviceGetRemappedRows, h)
            return {"correctable": int(corr), "uncorrectable": int(unc),
                    "pending": bool(pending), "failed": bool(failed)}
        if key == "bank_availability":
            v = self._call(n.nvmlDeviceGetRowRemapperHistogram, h)
            return {k: int(getattr(v, k)) for k in ("max", "high", "partial", "low", "none")}
        if key == "nvlink":
            states = []
            for link in range(getattr(n, "NVML_NVLINK_MAX_LINKS", 18)):
                try:
                    states.append(bool(self._call(n.nvmlDeviceGetNvLinkState, h, link)))
                except NvmlFail:
                    if not states:
                        raise
                    break  # No more links on this GPU.
            return {"links_total": len(states), "links_active": sum(states), "states": states}
        raise KeyError(key)

    def shutdown(self) -> None:
        try:
            self._n.nvmlShutdown()
        except Exception:
            pass


class RealProbe:
    mock = False
    fixture = None

    def run(self, argv: list, timeout: int = 120) -> CmdResult:
        started = utc_now()
        t0 = time.monotonic()
        try:
            p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        except FileNotFoundError:
            return CmdResult(argv, stderr=f"{argv[0]}: command not found", started_at=started, failure="not_found")
        except PermissionError as e:
            return CmdResult(argv, stderr=str(e), started_at=started, failure="permission")
        except subprocess.TimeoutExpired:
            return CmdResult(argv, stderr=f"timeout after {timeout} s", started_at=started, failure="timeout",
                             duration_ms=int((time.monotonic() - t0) * 1000))
        failure = None if p.returncode == 0 else classify_failure(p.stderr)
        return CmdResult(argv, p.stdout, p.stderr, p.returncode, started,
                         int((time.monotonic() - t0) * 1000), failure)

    def read_text(self, path: str) -> tuple[str | None, str | None]:
        """Return (text, None) or (None, failure)."""
        try:
            return Path(path).read_text(errors="replace"), None
        except FileNotFoundError:
            return None, "not_found"
        except PermissionError:
            return None, "permission"
        except OSError:
            return None, "exit_code"

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def env(self, name: str) -> str | None:
        return os.environ.get(name)

    def euid(self) -> int | None:
        return os.geteuid() if hasattr(os, "geteuid") else None

    def utc_offset_s(self) -> int:
        return int(datetime.now().astimezone().utcoffset().total_seconds())

    def nvml(self):
        return RealNvml()


# --- Mock (fixture) ----------------------------------------------------------

class MockNvml:
    def __init__(self, data: dict):
        if data.get("init_error"):
            raise NvmlFail(data["init_error"], "mock")
        self._d = data

    @staticmethod
    def _value(v):
        if isinstance(v, dict) and "$error" in v:
            raise NvmlFail(v["$error"], v.get("detail", "mock"))
        return v

    def version(self) -> str:
        return self._value(self._d["nvml_version"])

    def count(self) -> int:
        return len(self._d["devices"])

    def get(self, index: int, key: str):
        return self._value(self._d["devices"][index].get(key, {"$error": "not_supported"}))

    def shutdown(self) -> None:
        pass


class MockProbe:
    """Replays a fixture folder. See fixtures/README.md for the format."""

    mock = True

    def __init__(self, folder: Path, live_time: bool = False):
        """live_time: write the current time into the nvidia-smi XML, as a real node does."""
        self.folder = Path(folder)
        self.live_time = live_time
        self.fixture = self.folder.name
        self.spec = json.loads((self.folder / "fixture.json").read_text())
        nvml_file = self.spec.get("nvml_file")
        self.nvml_data = json.loads((self.folder / nvml_file).read_text()) if nvml_file else {"init_error": "missing"}
        bench_file = self.spec.get("bench_file")
        self.bench_data = json.loads((self.folder / bench_file).read_text()) if bench_file else {}

    def _content(self, item: dict, key_text: str, key_file: str) -> str:
        if key_file in item:
            return (self.folder / item[key_file]).read_text()
        return item.get(key_text, "")

    def run(self, argv: list, timeout: int = 120) -> CmdResult:
        item = self.spec.get("commands", {}).get(" ".join(argv))
        if item is None:
            return CmdResult(argv, stderr=f"{argv[0]}: command not found", started_at=utc_now(), failure="not_found")
        stdout = self._content(item, "stdout", "stdout_file")
        if self.live_time and "<timestamp>" in stdout:
            local = datetime.now(timezone.utc) + timedelta(seconds=self.utc_offset_s())
            stdout = re.sub(r"<timestamp>[^<]*</timestamp>", f"<timestamp>{local:%a %b %d %H:%M:%S %Y}</timestamp>", stdout, count=1)
        stderr = item.get("stderr", "")
        code = item.get("exit_code", 0)
        failure = None if code == 0 else classify_failure(stderr)
        return CmdResult(argv, stdout, stderr, code, utc_now(), 5, failure)

    def read_text(self, path: str) -> tuple[str | None, str | None]:
        item = self.spec.get("files", {}).get(path)
        if item is None:
            return None, "not_found"
        if "error" in item:
            return None, item["error"]
        return self._content(item, "text", "file"), None

    def exists(self, path: str) -> bool:
        return path in self.spec.get("paths", []) or path in self.spec.get("files", {})

    def env(self, name: str) -> str | None:
        return self.spec.get("env", {}).get(name)

    def euid(self) -> int | None:
        return self.spec.get("euid")

    def utc_offset_s(self) -> int:
        return self.spec.get("utc_offset_s", 0)

    def nvml(self):
        return MockNvml(self.nvml_data)


def resolve_fixture(name: str) -> Path:
    from . import text as T

    candidates = [Path(name)]
    if os.environ.get("DUD_FIXTURES_DIR"):
        candidates.append(Path(os.environ["DUD_FIXTURES_DIR"]) / name)
    candidates.append(REPO_FIXTURES / name)
    for c in candidates:
        if (c / "fixture.json").is_file():
            return c
    raise DudError(T.FIXTURE_NOT_FOUND.format(name=name))


def get_probe():
    if os.environ.get("DUD_MOCK") == "1":
        return MockProbe(resolve_fixture(os.environ.get("DUD_FIXTURE") or DEFAULT_FIXTURE), live_time=True)
    return RealProbe()
