from dud.collect import kernel_log, topo
from dud.collect.common import norm_bus, short_bus
from dud.probe import CmdResult
from conftest import FIXTURES, probe


def test_parse_xid_removes_pid_and_name():
    text = (FIXTURES / "h100_sxm_pending_remap" / "dmesg.txt").read_text()
    events = kernel_log.parse(text)
    assert [e["xid"] for e in events] == [94, 63, 79]
    assert events[0]["pci"] == "0000:18:00"
    assert events[0]["uptime_s"] == 8123.44219
    assert events[0]["message"].startswith("Contained: CE User Channel")
    for e in events:
        assert "pid=" not in e["message"] and "name=" not in e["message"]
    assert "other_tenant_job" not in kernel_log.format_event(events[2])


def test_parse_journalctl_format():
    line = "[ 1234.500000] secret-host kernel: NVRM: Xid (PCI:0000:3b:00): 48, pid=1, name=x, An uncorrectable double bit error"
    (e,) = kernel_log.parse(line)
    assert (e["xid"], e["pci"], e["uptime_s"]) == (48, "0000:3b:00", 1234.5)
    assert "secret-host" not in kernel_log.format_event(e)


def test_kernel_log_blocked():
    log = kernel_log.collect(probe("container_ecc_hidden"))
    assert log.events is None
    assert log.field["status"] == "blocked"
    assert log.field["reason"] == "permission_denied"


def test_kernel_log_ok_keeps_only_xid_lines():
    log = kernel_log.collect(probe("h100_sxm_healthy"))
    assert log.field["value"] == "dmesg"
    assert log.events == []
    assert log.text == ""


def test_events_for_one_gpu():
    log = kernel_log.collect(probe("h100_sxm_pending_remap"))
    f = kernel_log.events_field(log, "00000000:18:00.0")
    assert [e["xid"] for e in f["value"]] == [94, 63]


def test_bus_id_forms():
    assert norm_bus("0000:18:00.0") == "00000000:18:00.0"
    assert norm_bus("00000000:DB:00.0") == "00000000:db:00.0"
    assert short_bus("00000000:18:00.0") == "0000:18:00"


def test_topology_8_gpus():
    t = topo.parse((FIXTURES / "h100_sxm_healthy" / "nvidia-smi-topo-m.txt").read_text())
    assert t["columns"][:8] == [f"GPU{i}" for i in range(8)]
    assert t["rows"]["GPU0"]["GPU1"] == "NV18"
    assert t["rows"]["GPU3"]["GPU3"] == "X"
    assert t["rows"]["GPU0"]["CPU Affinity"] == "0-55,112-167"
    assert t["rows"]["GPU0"]["GPU NUMA ID"] == "N/A"
    assert t["rows"]["NIC0"]["GPU0"] == "PXB"


def test_topology_ansi_and_failure():
    text = "\x1b[1m\tGPU0\tCPU Affinity\x1b[0m\nGPU0\t X \t0-7\n"
    assert topo.parse(text)["rows"]["GPU0"] == {"GPU0": "X", "CPU Affinity": "0-7"}
    f = topo.field(CmdResult(["nvidia-smi"], failure="not_found", stderr="nvidia-smi: command not found"))
    assert (f["status"], f["reason"]) == ("error", "command_not_found")
    f = topo.field(CmdResult(["nvidia-smi"], stdout="garbage"))
    assert (f["status"], f["reason"]) == ("error", "parse_failed")
