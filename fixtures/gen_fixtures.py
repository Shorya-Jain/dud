#!/usr/bin/env python3
"""Generate the synthetic mock fixtures.

These fixtures copy the known format of nvidia-smi output, but they are not
from real GPUs. Fixtures from real GPUs go in their own folders and replace
these over time. Do not edit the generated files by hand. Edit this script and
run it again:

    python fixtures/gen_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

NEW_ECC = ["sram_correctable", "sram_uncorrectable_parity", "sram_uncorrectable_secded",
           "dram_correctable", "dram_uncorrectable"]
OLD_ECC = ["sram_correctable", "sram_uncorrectable", "dram_correctable", "dram_uncorrectable"]
SRAM_SOURCES = ["sram_l2", "sram_sm", "sram_microcontroller", "sram_pcie", "sram_other"]


def ecc_xml(style: str, volatile, aggregate) -> str:
    """volatile/aggregate: dict of counter -> value, or the string 'N/A' for the whole block."""
    if volatile == "N/A":
        return "\t\t<ecc_errors>N/A</ecc_errors>\n"
    keys = NEW_ECC if style == "new" else OLD_ECC

    def block(tag, values, agg):
        lines = [f"\t\t\t<{tag}>"]
        lines += [f"\t\t\t\t<{k}>{values.get(k, 0)}</{k}>" for k in keys]
        if agg and style == "new":
            lines.append("\t\t\t\t<sram_threshold_exceeded>No</sram_threshold_exceeded>")
        lines.append(f"\t\t\t</{tag}>")
        return "\n".join(lines)

    parts = ["\t\t<ecc_errors>", block("volatile", volatile, False), block("aggregate", aggregate, True)]
    if style == "new":
        parts.append("\t\t\t<aggregate_uncorrectable_sram_sources>")
        parts += [f"\t\t\t\t<{k}>0</{k}>" for k in SRAM_SOURCES]
        parts.append("\t\t\t</aggregate_uncorrectable_sram_sources>")
    parts.append("\t\t</ecc_errors>")
    return "\n".join(parts) + "\n"


def remap_xml(remap, histogram: bool) -> str:
    if remap == "N/A":
        return "\t\t<remapped_rows>N/A</remapped_rows>\n"
    hist = ""
    if histogram:
        mx, hi, pa, lo, no = remap["hist"]
        hist = (
            "\t\t\t<remapped_row_histogram>\n"
            f"\t\t\t\t<row_remap_histogram_max>{mx} bank(s)</row_remap_histogram_max>\n"
            f"\t\t\t\t<row_remap_histogram_high>{hi} bank(s)</row_remap_histogram_high>\n"
            f"\t\t\t\t<row_remap_histogram_partial>{pa} bank(s)</row_remap_histogram_partial>\n"
            f"\t\t\t\t<row_remap_histogram_low>{lo} bank(s)</row_remap_histogram_low>\n"
            f"\t\t\t\t<row_remap_histogram_none>{no} bank(s)</row_remap_histogram_none>\n"
            "\t\t\t</remapped_row_histogram>\n"
        )
    return (
        "\t\t<remapped_rows>\n"
        f"\t\t\t<remapped_row_corr>{remap['corr']}</remapped_row_corr>\n"
        f"\t\t\t<remapped_row_unc>{remap['unc']}</remapped_row_unc>\n"
        f"\t\t\t<remapped_row_pending>{remap['pending']}</remapped_row_pending>\n"
        f"\t\t\t<remapped_row_failure>{remap['failure']}</remapped_row_failure>\n"
        f"{hist}"
        "\t\t</remapped_rows>\n"
    )


def throttle_xml(style: str) -> str:
    tag, prefix = ("clocks_event_reasons", "clocks_event_reason") if style == "new" else \
        ("clocks_throttle_reasons", "clocks_throttle_reason")
    reasons = ["gpu_idle", "applications_clocks_setting", "sw_power_cap", "hw_slowdown",
               "hw_thermal_slowdown", "hw_power_brake_slowdown", "sync_boost", "sw_thermal_slowdown",
               "display_clocks_setting"]
    lines = [f"\t\t<{tag}>"]
    lines += [f"\t\t\t<{prefix}_{r}>{'Active' if r == 'gpu_idle' else 'Not Active'}</{prefix}_{r}>" for r in reasons]
    lines.append(f"\t\t</{tag}>")
    return "\n".join(lines) + "\n"


def power_xml(style: str, p: dict) -> str:
    if style == "new":
        return (
            "\t\t<gpu_power_readings>\n"
            "\t\t\t<power_state>P0</power_state>\n"
            f"\t\t\t<power_draw>{p['draw']:.2f} W</power_draw>\n"
            f"\t\t\t<current_power_limit>{p['default']:.2f} W</current_power_limit>\n"
            f"\t\t\t<requested_power_limit>{p['default']:.2f} W</requested_power_limit>\n"
            f"\t\t\t<default_power_limit>{p['default']:.2f} W</default_power_limit>\n"
            f"\t\t\t<min_power_limit>{p['min']:.2f} W</min_power_limit>\n"
            f"\t\t\t<max_power_limit>{p['max']:.2f} W</max_power_limit>\n"
            "\t\t</gpu_power_readings>\n"
            "\t\t<module_power_readings>\n"
            "\t\t\t<power_state>P0</power_state>\n"
            "\t\t\t<power_draw>N/A</power_draw>\n"
            "\t\t\t<current_power_limit>N/A</current_power_limit>\n"
            "\t\t</module_power_readings>\n"
        )
    return (
        "\t\t<power_readings>\n"
        "\t\t\t<power_state>P0</power_state>\n"
        "\t\t\t<power_management>Supported</power_management>\n"
        f"\t\t\t<power_draw>{p['draw']:.2f} W</power_draw>\n"
        f"\t\t\t<power_limit>{p['default']:.2f} W</power_limit>\n"
        f"\t\t\t<default_power_limit>{p['default']:.2f} W</default_power_limit>\n"
        f"\t\t\t<enforced_power_limit>{p['default']:.2f} W</enforced_power_limit>\n"
        f"\t\t\t<min_power_limit>{p['min']:.2f} W</min_power_limit>\n"
        f"\t\t\t<max_power_limit>{p['max']:.2f} W</max_power_limit>\n"
        "\t\t</power_readings>\n"
    )


def processes_xml(names: list) -> str:
    if not names:
        return "\t\t<processes>\n\t\t</processes>\n\t\t<accounted_processes>\n\t\t</accounted_processes>\n"
    body = "".join(
        "\t\t\t<process_info>\n"
        "\t\t\t\t<gpu_instance_id>N/A</gpu_instance_id>\n"
        "\t\t\t\t<compute_instance_id>N/A</compute_instance_id>\n"
        f"\t\t\t\t<pid>{4242 + i}</pid>\n"
        "\t\t\t\t<type>C</type>\n"
        f"\t\t\t\t<process_name>{n}</process_name>\n"
        "\t\t\t\t<used_memory>1024 MiB</used_memory>\n"
        "\t\t\t</process_info>\n" for i, n in enumerate(names))
    return f"\t\t<processes>\n{body}\t\t</processes>\n\t\t<accounted_processes>\n\t\t</accounted_processes>\n"


def gpu_xml(g: dict) -> str:
    style = g["style"]
    bus = g["bus"]
    n = (
        f'\t<gpu id="00000000:{bus}:00.0">\n'
        f"\t\t<product_name>{g['name']}</product_name>\n"
        "\t\t<product_brand>NVIDIA</product_brand>\n"
        f"\t\t<product_architecture>{g['arch']}</product_architecture>\n"
        "\t\t<display_mode>Disabled</display_mode>\n"
        "\t\t<display_active>Disabled</display_active>\n"
        "\t\t<persistence_mode>Enabled</persistence_mode>\n"
        "\t\t<mig_mode>\n\t\t\t<current_mig>Disabled</current_mig>\n\t\t\t<pending_mig>Disabled</pending_mig>\n\t\t</mig_mode>\n"
        "\t\t<mig_devices>\n\t\t\tNone\n\t\t</mig_devices>\n"
        "\t\t<accounting_mode>Disabled</accounting_mode>\n"
        "\t\t<accounting_mode_buffer_size>4000</accounting_mode_buffer_size>\n"
        f"\t\t<serial>{g['serial']}</serial>\n"
        f"\t\t<uuid>{g['uuid']}</uuid>\n"
        f"\t\t<minor_number>{g['minor']}</minor_number>\n"
        f"\t\t<vbios_version>{g['vbios']}</vbios_version>\n"
        "\t\t<multigpu_board>No</multigpu_board>\n"
        f"\t\t<board_id>0x{bus}00</board_id>\n"
        f"\t\t<board_part_number>{g['board_pn']}</board_part_number>\n"
        f"\t\t<gpu_module_id>{g['minor'] + 1}</gpu_module_id>\n"
        "\t\t<inforom_version>\n"
        f"\t\t\t<img_version>{g['inforom']}</img_version>\n"
        "\t\t\t<oem_object>2.1</oem_object>\n"
        "\t\t\t<ecc_object>7.16</ecc_object>\n"
        "\t\t\t<pwr_object>N/A</pwr_object>\n"
        "\t\t</inforom_version>\n"
        f"\t\t<gsp_firmware_version>{g['gsp']}</gsp_firmware_version>\n"
        "\t\t<gpu_virtualization_mode>\n"
        f"\t\t\t<virtualization_mode>{g.get('virt_mode', 'None')}</virtualization_mode>\n"
        "\t\t\t<host_vgpu_mode>N/A</host_vgpu_mode>\n"
        "\t\t</gpu_virtualization_mode>\n"
        "\t\t<gpu_reset_status>\n"
        f"\t\t\t<reset_required>{g['reset_required']}</reset_required>\n"
        "\t\t\t<drain_and_reset_recommended>N/A</drain_and_reset_recommended>\n"
        "\t\t</gpu_reset_status>\n"
        "\t\t<pci>\n"
        f"\t\t\t<pci_bus>{bus}</pci_bus>\n"
        "\t\t\t<pci_device>00</pci_device>\n"
        "\t\t\t<pci_domain>0000</pci_domain>\n"
        f"\t\t\t<pci_device_id>{g['dev_id']}</pci_device_id>\n"
        f"\t\t\t<pci_bus_id>00000000:{bus}:00.0</pci_bus_id>\n"
        f"\t\t\t<pci_sub_system_id>{g['subsys']}</pci_sub_system_id>\n"
        "\t\t\t<pci_gpu_link_info>\n"
        "\t\t\t\t<pcie_gen>\n"
        f"\t\t\t\t\t<max_link_gen>{g['pcie_max']}</max_link_gen>\n"
        f"\t\t\t\t\t<current_link_gen>{g['pcie_cur']}</current_link_gen>\n"
        f"\t\t\t\t\t<device_current_link_gen>{g['pcie_cur']}</device_current_link_gen>\n"
        f"\t\t\t\t\t<max_device_link_gen>{g['pcie_max']}</max_device_link_gen>\n"
        f"\t\t\t\t\t<max_host_link_gen>{g['pcie_max']}</max_host_link_gen>\n"
        "\t\t\t\t</pcie_gen>\n"
        "\t\t\t\t<link_widths>\n"
        "\t\t\t\t\t<max_link_width>16x</max_link_width>\n"
        f"\t\t\t\t\t<current_link_width>{g.get('width_cur', '16x')}</current_link_width>\n"
        "\t\t\t\t</link_widths>\n"
        "\t\t\t</pci_gpu_link_info>\n"
        f"\t\t\t<replay_counter>{g.get('replay', 0)}</replay_counter>\n"
        "\t\t\t<replay_rollover_counter>0</replay_rollover_counter>\n"
        "\t\t\t<tx_util>0 KB/s</tx_util>\n"
        "\t\t\t<rx_util>0 KB/s</rx_util>\n"
        "\t\t</pci>\n"
        "\t\t<fan_speed>N/A</fan_speed>\n"
        "\t\t<performance_state>P0</performance_state>\n"
        + throttle_xml(style) +
        "\t\t<fb_memory_usage>\n"
        f"\t\t\t<total>{g['mem_mib']} MiB</total>\n"
        "\t\t\t<reserved>328 MiB</reserved>\n"
        "\t\t\t<used>0 MiB</used>\n"
        f"\t\t\t<free>{g['mem_mib'] - 328} MiB</free>\n"
        "\t\t</fb_memory_usage>\n"
        "\t\t<compute_mode>Default</compute_mode>\n"
        "\t\t<utilization>\n\t\t\t<gpu_util>0 %</gpu_util>\n\t\t\t<memory_util>0 %</memory_util>\n\t\t</utilization>\n"
        "\t\t<ecc_mode>\n"
        f"\t\t\t<current_ecc>{g.get('ecc_mode', 'Enabled')}</current_ecc>\n"
        f"\t\t\t<pending_ecc>{g.get('ecc_mode', 'Enabled')}</pending_ecc>\n"
        "\t\t</ecc_mode>\n"
        + ecc_xml(style, g["ecc_vol"], g["ecc_agg"]) +
        "\t\t<retired_pages>\n"
        "\t\t\t<multiple_single_bit_retirement>\n\t\t\t\t<retired_count>N/A</retired_count>\n\t\t\t\t<retired_pagelist>N/A</retired_pagelist>\n\t\t\t</multiple_single_bit_retirement>\n"
        "\t\t\t<double_bit_retirement>\n\t\t\t\t<retired_count>N/A</retired_count>\n\t\t\t\t<retired_pagelist>N/A</retired_pagelist>\n\t\t\t</double_bit_retirement>\n"
        "\t\t\t<pending_blacklist>N/A</pending_blacklist>\n"
        "\t\t\t<pending_retirement>N/A</pending_retirement>\n"
        "\t\t</retired_pages>\n"
        + remap_xml(g["remap"], g.get("histogram", True)) +
        "\t\t<temperature>\n"
        f"\t\t\t<gpu_temp>{g['temp']} C</gpu_temp>\n"
        "\t\t\t<gpu_temp_max_threshold>92 C</gpu_temp_max_threshold>\n"
        "\t\t\t<gpu_temp_slow_threshold>89 C</gpu_temp_slow_threshold>\n"
        f"\t\t\t<memory_temp>{g['mem_temp']}</memory_temp>\n"
        "\t\t</temperature>\n"
        + power_xml(style, g["power"]) +
        "\t\t<clocks>\n"
        f"\t\t\t<graphics_clock>345 MHz</graphics_clock>\n\t\t\t<sm_clock>345 MHz</sm_clock>\n"
        f"\t\t\t<mem_clock>{g['mem_mhz']} MHz</mem_clock>\n"
        "\t\t</clocks>\n"
        "\t\t<max_clocks>\n"
        f"\t\t\t<graphics_clock>{g['sm_mhz']} MHz</graphics_clock>\n"
        f"\t\t\t<sm_clock>{g['sm_mhz']} MHz</sm_clock>\n"
        f"\t\t\t<mem_clock>{g['mem_mhz']} MHz</mem_clock>\n"
        "\t\t</max_clocks>\n"
        "\t\t<fabric>\n"
        f"\t\t\t<state>{g.get('fabric', 'N/A')}</state>\n"
        f"\t\t\t<status>{'Success' if g.get('fabric') == 'Completed' else 'N/A'}</status>\n"
        "\t\t</fabric>\n"
        + processes_xml(g.get("processes", [])) +
        "\t</gpu>\n"
    )
    return n


def smi_xml(driver: str, cuda: str, gpus: list) -> str:
    return (
        '<?xml version="1.0" ?>\n'
        '<!DOCTYPE nvidia_smi_log SYSTEM "nvsmi_device_v12.dtd">\n'
        "<nvidia_smi_log>\n"
        "\t<timestamp>Sat Oct 31 12:00:00 2026</timestamp>\n"
        f"\t<driver_version>{driver}</driver_version>\n"
        f"\t<cuda_version>{cuda}</cuda_version>\n"
        f"\t<attached_gpus>{len(gpus)}</attached_gpus>\n"
        + "".join(gpu_xml(g) for g in gpus) +
        "</nvidia_smi_log>\n"
    )


def topo_txt(n: int, link: str, cpu: str, nic: bool = False) -> str:
    names = [f"GPU{i}" for i in range(n)]
    header = "\t" + "\t".join(names + (["NIC0"] if nic else []) + ["CPU Affinity", "NUMA Affinity", "GPU NUMA ID"])
    rows = []
    for i in range(n):
        cells = [" X " if j == i else link for j in range(n)]
        if nic:
            cells.append("PXB" if i < 2 else "SYS")
        cells += [cpu, "0" if i < n / 2 or n == 1 else "1", "", "N/A"]  # Real output has a double tab here.
        rows.append(f"GPU{i}\t" + "\t".join(cells))
    if nic:
        rows.append("NIC0\t" + "\t".join(["PXB" if i < 2 else "SYS" for i in range(n)]) + "\t X \t\t\t")
    legend = (
        "\nLegend:\n\n"
        "  X    = Self\n"
        "  SYS  = Connection traversing PCIe as well as the SMP interconnect between NUMA nodes (e.g., QPI/UPI)\n"
        "  NODE = Connection traversing PCIe as well as the interconnect between PCIe Host Bridges within a NUMA node\n"
        "  PHB  = Connection traversing PCIe as well as a PCIe Host Bridge (typically the CPU)\n"
        "  PXB  = Connection traversing multiple PCIe bridges (without traversing the PCIe Host Bridge)\n"
        "  PIX  = Connection traversing at most a single PCIe bridge\n"
        "  NV#  = Connection traversing a bonded set of # NVLinks\n"
    )
    if nic:
        legend += "\nNIC Legend:\n\n  NIC0: mlx5_0\n"
    return header + "\n" + "\n".join(rows) + "\n" + legend


def nvml_json(version: str, gpus: list, nvlink, remap_override=None, hist_override=None) -> dict:
    devices = []
    for g in gpus:
        remap = g["remap"]
        devices.append({
            "pci_bus_id": f"00000000:{g['bus']}:00.0",
            "uuid": g["uuid"],
            "memory_total_bytes": g["mem_mib"] * 1048576,
            "remapped_rows": remap_override or {
                "correctable": remap["corr"], "uncorrectable": remap["unc"],
                "pending": remap["pending"] == "Yes", "failed": remap["failure"] == "Yes"},
            "bank_availability": hist_override or dict(zip(["max", "high", "partial", "low", "none"], remap["hist"])),
            "nvlink": nvlink,
        })
    return {"nvml_version": version, "devices": devices}


def cmd(stdout_file=None, stdout=None, exit_code=0, stderr=""):
    out = {"exit_code": exit_code}
    if stdout_file:
        out["stdout_file"] = stdout_file
    if stdout is not None:
        out["stdout"] = stdout
    if stderr:
        out["stderr"] = stderr
    return out


def write_fixture(name: str, description: str, xml: str, topo: str, nvml: dict, spec: dict,
                  dmesg: str | None = None) -> None:
    d = HERE / name
    d.mkdir(exist_ok=True)
    (d / "nvidia-smi-q-x.xml").write_text(xml)
    (d / "nvidia-smi-topo-m.txt").write_text(topo)
    (d / "nvml.json").write_text(json.dumps(nvml, indent=2) + "\n")
    commands = {
        "nvidia-smi -q -x": cmd("nvidia-smi-q-x.xml"),
        "nvidia-smi topo -m": cmd("nvidia-smi-topo-m.txt"),
    }
    if dmesg is not None:
        (d / "dmesg.txt").write_text(dmesg)
        commands["dmesg"] = cmd("dmesg.txt")
    commands.update(spec.pop("commands", {}))
    full = {"description": description, "synthetic": True, "commands": commands, "nvml_file": "nvml.json"}
    full.update(spec)
    (d / "fixture.json").write_text(json.dumps(full, indent=2) + "\n")


ZERO = {}
UBUNTU = {"text": 'PRETTY_NAME="Ubuntu 22.04.4 LTS"\nNAME="Ubuntu"\nVERSION_ID="22.04"\n'}


def h100_sxm(i: int, bus: str, **kw) -> dict:
    g = dict(
        style="new", bus=bus, minor=i, name="NVIDIA H100 80GB HBM3", arch="Hopper",
        serial=f"165292200{1000 + i}", uuid=f"GPU-5e1a7c3d-90b2-4f61-8c3e-a1b2c3d4e5{i:02d}",
        vbios="96.00.99.00.01", board_pn="692-2G520-0200-000", dev_id="233010DE", subsys="16C110DE",
        inforom="G520.0200.00.05", gsp="550.90.07", reset_required="No", pcie_max=5, pcie_cur=5,
        mem_mib=81559, temp=31 + i, mem_temp="38 C", sm_mhz=1980, mem_mhz=2619, fabric="Completed",
        power={"draw": 70.5 + i, "default": 700, "min": 200, "max": 700},
        ecc_vol=ZERO, ecc_agg=ZERO, remap={"corr": 0, "unc": 0, "pending": "No", "failure": "No", "hist": (2560, 0, 0, 0, 0)},
    )
    g.update(kw)
    return g


def main() -> None:
    # 1. Healthy 8x H100 SXM node, bare metal in a VM. One GPU has a few old correctable errors.
    gpus = [h100_sxm(i, b) for i, b in enumerate(["18", "2a", "3a", "5d", "9a", "ab", "ba", "db"])]
    gpus[0]["processes"] = ["/usr/bin/python3 train_secret_model.py"]
    gpus[3]["ecc_agg"] = {"dram_correctable": 12}
    write_fixture(
        "h100_sxm_healthy",
        "8x H100 SXM5 80GB, driver 550, KVM VM, root, readable kernel log, NVLink NV18 between all GPUs.",
        smi_xml("550.90.07", "12.4", gpus),
        topo_txt(8, "NV18", "0-55,112-167", nic=True),
        nvml_json("12.550.90.07", gpus, {"links_total": 18, "links_active": 18, "states": [True] * 18}),
        {
            "commands": {"uname -r": cmd(stdout="5.15.0-105-generic\n"),
                         "systemd-detect-virt": cmd(stdout="kvm\n")},
            "files": {"/etc/os-release": UBUNTU,
                      "/proc/cpuinfo": {"text": "processor\t: 0\nmodel name\t: Intel(R) Xeon(R) Platinum 8480+\nflags\t\t: fpu vme hypervisor avx512f\n"},
                      "/sys/class/dmi/id/sys_vendor": {"text": "QEMU\n"},
                      "/sys/class/dmi/id/product_name": {"text": "Standard PC (Q35 + ICH9, 2009)\n"},
                      "/proc/1/cgroup": {"text": "0::/init.scope\n"}},
            "euid": 0,
            "utc_offset_s": 0,
        },
        dmesg=(
            "[    0.000000] Linux version 5.15.0-105-generic (buildd@lcy02-amd64-007)\n"
            "[    1.204512] systemd[1]: Set hostname to <secret-host-01>.\n"
            "[    4.882910] nvidia: loading out-of-tree module taints kernel.\n"
            "[    5.017334] NVRM: loading NVIDIA UNIX x86_64 Kernel Module  550.90.07  Fri May 31 09:35:42 UTC 2024\n"
        ),
    )

    # 2. One H100 SXM with a pending row remap after uncorrectable errors.
    g = h100_sxm(0, "18", serial="1652922009999", uuid="GPU-0bad0c0d-1e2f-4a5b-9c8d-7e6f5a4b3c2d",
                 reset_required="Yes",
                 ecc_vol={"dram_uncorrectable": 2, "dram_correctable": 5},
                 ecc_agg={"dram_uncorrectable": 2, "dram_correctable": 41},
                 remap={"corr": 3, "unc": 1, "pending": "Yes", "failure": "No", "hist": (2556, 4, 0, 0, 0)})
    write_fixture(
        "h100_sxm_pending_remap",
        "1x H100 SXM5 80GB (one GPU of an 8-GPU board), pending row remap, uncorrectable ECC errors, XID 94 and 63.",
        smi_xml("550.90.07", "12.4", [g]),
        topo_txt(1, "", "0-27"),
        nvml_json("12.550.90.07", [g], {"links_total": 18, "links_active": 18, "states": [True] * 18}),
        {
            "commands": {"uname -r": cmd(stdout="5.15.0-105-generic\n"),
                         "systemd-detect-virt": cmd(stdout="kvm\n")},
            "files": {"/etc/os-release": UBUNTU,
                      "/proc/cpuinfo": {"text": "model name\t: AMD EPYC 9454 48-Core Processor\nflags\t\t: fpu hypervisor\n"}},
            "paths": ["/.dockerenv"],
            "euid": 0,
            "utc_offset_s": 0,
        },
        dmesg=(
            "[    5.017334] NVRM: loading NVIDIA UNIX x86_64 Kernel Module  550.90.07\n"
            "[ 8123.442190] NVRM: Xid (PCI:0000:18:00): 94, pid=51234, name=python3, Contained: CE User Channel (0x9). RST: No, D-RST: No\n"
            "[ 8123.442877] NVRM: Xid (PCI:0000:18:00): 63, pid='<unknown>', name=<unknown>, Row Remapper: New row (0x00000001c3f2a000) Marked for Remapping, reset gpu to activate.\n"
            "[ 9001.000001] NVRM: Xid (PCI:0000:2a:00): 79, pid=777, name=other_tenant_job, GPU has fallen off the bus.\n"
        ),
    )

    # 3. One A100 80GB PCIe in a Docker container with an older driver (old XML format, no bank histogram).
    a = dict(
        style="old", bus="41", minor=0, name="NVIDIA A100 80GB PCIe", arch="Ampere",
        serial="1323621001234", uuid="GPU-a100a100-2b3c-4d5e-8f90-123456789abc",
        vbios="92.00.90.00.04", board_pn="900-21001-0020-100", dev_id="20B510DE", subsys="153310DE",
        inforom="G262.0230.00.04", gsp="N/A", reset_required="No", pcie_max=4, pcie_cur=1,
        mem_mib=81920, temp=34, mem_temp="N/A", sm_mhz=1410, mem_mhz=1512,
        power={"draw": 45.12, "default": 300, "min": 150, "max": 300},
        ecc_vol=ZERO, ecc_agg={"dram_correctable": 3},
        remap={"corr": 0, "unc": 0, "pending": "No", "failure": "No", "hist": (640, 0, 0, 0, 0)},
        histogram=False,
    )
    write_fixture(
        "a100_80gb_pcie",
        "1x A100 80GB PCIe, driver 525 (old XML format, no bank histogram in XML), Docker, kernel log blocked.",
        smi_xml("525.147.05", "12.0", [a]),
        topo_txt(1, "", "0-15"),
        nvml_json("12.525.147.05", [a], {"$error": "not_supported"}),
        {
            "commands": {
                "dmesg": cmd(exit_code=1, stderr="dmesg: read kernel buffer failed: Operation not permitted\n"),
                "uname -r": cmd(stdout="5.4.0-150-generic\n"),
            },
            "files": {"/etc/os-release": UBUNTU,
                      "/proc/cpuinfo": {"text": "model name\t: AMD EPYC 7543 32-Core Processor\nflags\t\t: fpu sse2\n"},
                      "/proc/1/cgroup": {"text": "12:devices:/docker/3f9a1c\n"}},
            "paths": ["/.dockerenv"],
            "euid": 0,
            "utc_offset_s": 0,
        },
    )

    # 4. Two H100 PCIe in a Kubernetes pod in a VM. The provider hides ECC and row remap data.
    hidden = []
    for i, bus in enumerate(["17", "65"]):
        hidden.append(dict(
            style="new", bus=bus, minor=i, name="NVIDIA H100 PCIe", arch="Hopper",
            serial=f"132112300{4000 + i}", uuid=f"GPU-c0ffee00-{i:04d}-4abc-9def-0123456789ab",
            vbios="96.00.5E.00.01", board_pn="900-21010-0000-000", dev_id="233110DE", subsys="162610DE",
            inforom="G520.0210.00.03", gsp="550.54.15", reset_required="N/A", pcie_max=5, pcie_cur=5,
            mem_mib=81559, temp=30, mem_temp="N/A", sm_mhz=1755, mem_mhz=1593, virt_mode="Pass-Through",
            power={"draw": 48.0, "default": 350, "min": 200, "max": 350},
            ecc_mode="N/A", ecc_vol="N/A", ecc_agg="N/A", remap="N/A",
        ))
    nv = nvml_json("12.550.54.15", [dict(h, remap={"corr": 0, "unc": 0, "pending": "No", "failure": "No",
                                                   "hist": (0, 0, 0, 0, 0)}) for h in hidden],
                   {"$error": "not_supported"},
                   remap_override={"$error": "no_permission"}, hist_override={"$error": "no_permission"})
    write_fixture(
        "container_ecc_hidden",
        "2x H100 PCIe in a Kubernetes pod in a VM. ECC and row remap data show N/A. Not root. No kernel log.",
        smi_xml("550.54.15", "12.4", hidden),
        topo_txt(2, "NODE", "0-31"),
        nv,
        {
            "commands": {
                "dmesg": cmd(exit_code=1, stderr="dmesg: read kernel buffer failed: Operation not permitted\n"),
                "journalctl -k --no-pager -o short-monotonic": cmd(stdout="No journal files were found.\n-- No entries --\n"),
                "uname -r": cmd(stdout="6.2.0-39-generic\n"),
                "systemd-detect-virt": cmd(stdout="kvm\n"),
            },
            "files": {"/etc/os-release": UBUNTU,
                      "/proc/cpuinfo": {"text": "model name\t: Intel(R) Xeon(R) Platinum 8462Y+\nflags\t\t: fpu hypervisor\n"},
                      "/sys/class/dmi/id/sys_vendor": {"error": "permission"}},
            "env": {"KUBERNETES_SERVICE_HOST": "10.96.0.1"},
            "euid": 1000,
            "utc_offset_s": -25200,
        },
    )


if __name__ == "__main__":
    main()
