"""Node facts: operating system, CPU, container and VM detection."""
from __future__ import annotations

from ..model import missing, ok
from .common import cmd_failure_field

SRC = "os"
_CONTAINER_KEYS = ("kubepods", "docker", "containerd", "libpod", "lxc")


def _file_value(probe, path: str) -> dict:
    text, failure = probe.read_text(path)
    if text is None:
        if failure == "permission":
            return missing("blocked", SRC, "permission_denied", path)
        return missing("not_supported" if failure == "not_found" else "error", SRC,
                       "file_not_found" if failure == "not_found" else "command_failed", path)
    value = text.strip()
    return ok(value, SRC) if value else missing("not_supported", SRC, "file_empty", path)


def _os_release(probe) -> dict:
    text, _ = probe.read_text("/etc/os-release")
    for line in (text or "").splitlines():
        if line.startswith("PRETTY_NAME="):
            return ok(line.split("=", 1)[1].strip().strip('"'), SRC)
    return missing("not_supported", SRC, "file_not_found", "/etc/os-release")


def _cpu(probe) -> tuple[dict, str | None]:
    text, failure = probe.read_text("/proc/cpuinfo")
    if text is None:
        return missing("not_supported", SRC, "file_not_found", "/proc/cpuinfo"), None
    for line in text.splitlines():
        if line.lower().startswith("model name"):
            return ok(line.split(":", 1)[1].strip(), SRC), text
    return missing("not_supported", SRC, "not_in_output", "/proc/cpuinfo"), text


def _container(probe) -> dict:
    if probe.exists("/.dockerenv"):
        return ok("docker", SRC)
    if probe.exists("/run/.containerenv"):
        return ok("podman", SRC)
    if probe.env("KUBERNETES_SERVICE_HOST"):
        return ok("kubernetes", SRC)
    cgroup, _ = probe.read_text("/proc/1/cgroup")
    for key in _CONTAINER_KEYS:
        if cgroup and key in cgroup:
            return ok(key, SRC)
    return ok("none", SRC)


def _virtualization(probe, cpuinfo: str | None) -> dict:
    r = probe.run(["systemd-detect-virt"])
    out = r.stdout.strip()
    if out:  # Prints "none" with exit code 1 on bare metal.
        return ok(out, SRC)
    if cpuinfo is not None:
        flags = next((l for l in cpuinfo.splitlines() if l.startswith("flags")), "")
        return ok("unknown_hypervisor" if " hypervisor" in flags else "none", SRC)
    return cmd_failure_field(r, SRC, None)


def _uname(probe) -> dict:
    r = probe.run(["uname", "-r"])
    return ok(r.stdout.strip(), SRC) if r.ok and r.stdout.strip() else cmd_failure_field(r, SRC, None)


def collect(probe, top: dict, nvml_version: dict, topology: dict, kernel_log: dict) -> dict:
    cpu_model, cpuinfo = _cpu(probe)
    euid = probe.euid()
    return {
        "driver_version": top["driver_version"],
        "cuda_driver_version": top["cuda_version"],
        "nvml_version": nvml_version,
        "smi_timestamp": top["timestamp"],
        "attached_gpus": top["attached_gpus"],
        "os": _os_release(probe),
        "kernel": _uname(probe),
        "cpu_model": cpu_model,
        "environment": {
            "container": _container(probe),
            "virtualization": _virtualization(probe, cpuinfo),
            "dmi_vendor": _file_value(probe, "/sys/class/dmi/id/sys_vendor"),
            "dmi_product": _file_value(probe, "/sys/class/dmi/id/product_name"),
            "is_root": ok(euid == 0, SRC) if euid is not None else missing("not_supported", SRC, "not_in_output"),
        },
        "kernel_log": kernel_log,
        "topology": topology,
    }
