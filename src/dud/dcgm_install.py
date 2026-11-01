"""Install DCGM when `dud full` cannot find `dcgmi`.

dud installs DCGM 4 from the NVIDIA CUDA package source, with apt. This works on
Ubuntu and Debian nodes, as root or with sudo. On other nodes dud shows why it
cannot install DCGM, and the full test continues without the DCGM diagnostic.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import text as T

REPO_URL = "https://developer.download.nvidia.com/compute/cuda/repos/{distro}/{arch}/"
KEYRING = "cuda-keyring_1.1-1_all.deb"
PACKAGE = "datacenter-gpu-manager-4-cuda{major}"
_ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "sbsa", "arm64": "sbsa"}
_DISTROS = ("ubuntu", "debian")


def os_release(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def plan(release: dict, machine: str, cuda_version: str | None) -> tuple:
    """Return (plan, None) or (None, reason). The plan has the package source and the package name."""
    distro_id = release.get("ID", "").lower()
    version = release.get("VERSION_ID", "")
    if distro_id not in _DISTROS or not version:
        return None, T.DCGM_INSTALL_OS.format(os=release.get("PRETTY_NAME") or distro_id or "unknown")
    arch = _ARCH.get(machine.lower())
    if arch is None:
        return None, T.DCGM_INSTALL_ARCH.format(arch=machine)
    major = (cuda_version or "").split(".")[0]
    if not major.isdigit():
        return None, T.DCGM_INSTALL_NO_CUDA
    # The package source names Debian by its major version only (debian12), and Ubuntu as ubuntu2204.
    distro = f"debian{version.split('.')[0]}" if distro_id == "debian" else f"ubuntu{version.replace('.', '')}"
    return {"repo": REPO_URL.format(distro=distro, arch=arch), "package": PACKAGE.format(major=major)}, None


def _sudo() -> list | None:
    """[] for root, ["sudo"] if sudo exists, else None."""
    if os.geteuid() == 0:
        return []
    return ["sudo"] if shutil.which("sudo") else None


def _has_keyring() -> bool:
    return subprocess.call(["dpkg", "-s", "cuda-keyring"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def install(p: dict, sudo: list, say) -> bool:
    """Add the NVIDIA package source (if necessary) and install DCGM. Return True if dcgmi is then available."""
    try:
        if not _has_keyring():
            with tempfile.TemporaryDirectory() as tmp:
                deb = Path(tmp) / KEYRING
                urllib.request.urlretrieve(p["repo"] + KEYRING, deb)
                if subprocess.call(sudo + ["dpkg", "-i", str(deb)]) != 0:
                    return False
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        if subprocess.call(sudo + ["apt-get", "update"], env=env) != 0:
            return False
        cmd = sudo + ["apt-get", "install", "-y", "--install-recommends", p["package"]]
        if subprocess.call(cmd, env=env) != 0:
            return False
    except OSError as e:
        say(T.DCGM_INSTALL_FAILED.format(detail=e))
        return False
    return shutil.which("dcgmi") is not None


def offer(doc: dict, say, assume_yes: bool = False) -> bool:
    """If dcgmi is missing, ask the user and install DCGM. Return True if dcgmi is available after."""
    if shutil.which("dcgmi"):
        return True
    say(T.DCGM_MISSING)
    if not sys.platform.startswith("linux") or not shutil.which("apt-get"):
        say(T.DCGM_INSTALL_NO_APT)
        return False
    try:
        release = os_release(Path("/etc/os-release").read_text())
    except OSError:
        release = {}
    cuda = (doc.get("host", {}).get("cuda_driver_version") or {}).get("value")
    p, reason = plan(release, platform.machine(), cuda)
    if p is None:
        say(reason)
        return False
    sudo = _sudo()
    if sudo is None:
        say(T.DCGM_INSTALL_NOT_ROOT)
        return False
    if not assume_yes:
        if not sys.stdin.isatty():
            say(T.DCGM_INSTALL_NO_TERMINAL)
            return False
        if input(T.DCGM_ASK.format(package=p["package"])).strip().lower() not in ("", "y", "yes"):
            return False
    say(T.DCGM_INSTALL_START.format(package=p["package"]))
    if install(p, sudo, say):
        say(T.DCGM_INSTALL_DONE)
        return True
    say(T.DCGM_INSTALL_FAILED.format(detail=T.DCGM_INSTALL_SEE_OUTPUT))
    return False
