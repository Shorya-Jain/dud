"""DCGM install: package selection, and when dud asks, installs or skips."""
import pytest

from dud import dcgm_install as di
from dud import text as T

UBUNTU = di.os_release('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"\nPRETTY_NAME="Ubuntu 22.04.4 LTS"\n')
DOC = {"host": {"cuda_driver_version": {"value": "12.4", "status": "ok"}}}


def test_plan_ubuntu_x86():
    p, reason = di.plan(UBUNTU, "x86_64", "12.4")
    assert reason is None
    assert p == {"repo": "https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/",
                 "package": "datacenter-gpu-manager-4-cuda12"}


def test_plan_debian_arm_cuda13():
    p, _ = di.plan({"ID": "debian", "VERSION_ID": "12"}, "aarch64", "13.0")
    assert p["repo"].endswith("/repos/debian12/sbsa/")
    assert p["package"] == "datacenter-gpu-manager-4-cuda13"


@pytest.mark.parametrize("release,machine,cuda,text", [
    ({"ID": "rhel", "VERSION_ID": "9", "PRETTY_NAME": "RHEL 9"}, "x86_64", "12.4", "RHEL 9"),
    (UBUNTU, "ppc64le", "12.4", "ppc64le"),
    (UBUNTU, "x86_64", None, "CUDA version"),
    (UBUNTU, "x86_64", "N/A", "CUDA version"),
])
def test_plan_refuses(release, machine, cuda, text):
    p, reason = di.plan(release, machine, cuda)
    assert p is None and text in reason


@pytest.fixture
def node(monkeypatch):
    """A Linux node with apt and Ubuntu 22.04, as root, without dcgmi."""
    state = {"installed": False, "calls": [], "answer": "y", "tty": True}

    def which(name):
        if name == "dcgmi":
            return "/usr/bin/dcgmi" if state["installed"] else None
        return f"/usr/bin/{name}"

    def install(p, sudo, say):
        state["calls"].append((p["package"], sudo))
        state["installed"] = True
        return True

    monkeypatch.setattr(di.shutil, "which", which)
    monkeypatch.setattr(di.sys, "platform", "linux")
    monkeypatch.setattr(di.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(di, "os_release", lambda text: UBUNTU)
    monkeypatch.setattr(di.Path, "read_text", lambda self: "")
    monkeypatch.setattr(di.os, "geteuid", lambda: 0)
    monkeypatch.setattr(di, "install", install)
    monkeypatch.setattr(di.sys.stdin, "isatty", lambda: state["tty"], raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt: state["answer"])
    return state


def test_offer_does_nothing_when_installed(node):
    node["installed"] = True
    said = []
    assert di.offer(DOC, said.append) is True
    assert node["calls"] == [] and said == []


@pytest.mark.parametrize("answer", ["", "y", "YES"])
def test_offer_installs_on_yes(node, answer):
    node["answer"] = answer
    said = []
    assert di.offer(DOC, said.append) is True
    assert node["calls"] == [("datacenter-gpu-manager-4-cuda12", [])]
    assert said[-1] == T.DCGM_INSTALL_DONE


def test_offer_skips_on_no(node):
    node["answer"] = "n"
    assert di.offer(DOC, lambda s: None) is False
    assert node["calls"] == []


def test_offer_no_terminal_needs_flag(node):
    node["tty"] = False
    said = []
    assert di.offer(DOC, said.append) is False
    assert said[-1] == T.DCGM_INSTALL_NO_TERMINAL
    assert di.offer(DOC, said.append, assume_yes=True) is True


def test_offer_uses_sudo_when_not_root(node, monkeypatch):
    monkeypatch.setattr(di.os, "geteuid", lambda: 1000)
    assert di.offer(DOC, lambda s: None) is True
    assert node["calls"][0][1] == ["sudo"]


def test_offer_without_apt(node, monkeypatch):
    monkeypatch.setattr(di.shutil, "which", lambda name: None)
    said = []
    assert di.offer(DOC, said.append) is False
    assert said[-1] == T.DCGM_INSTALL_NO_APT and node["calls"] == []
