# Fixtures

A fixture is a folder of recorded raw output. Mock mode (`DUD_MOCK=1`) uses it in place of a real node.

The four fixtures here are synthetic. `gen_fixtures.py` makes them from the known nvidia-smi format.
Do not edit them by hand. Edit `gen_fixtures.py` and run it again.
Fixtures from real GPUs go in new folders, with `"synthetic": false` in `fixture.json`.

| Fixture | What it shows |
|---|---|
| `h100_sxm_healthy` | 8x H100 SXM, driver 550, VM, root, readable kernel log, NVLink between all GPUs |
| `h100_sxm_pending_remap` | 1x H100 SXM, pending row remap, uncorrectable ECC errors, XID 94 and 63 |
| `a100_80gb_pcie` | 1x A100 80GB PCIe, driver 525 (old XML format), Docker, kernel log blocked |
| `container_ecc_hidden` | 2x H100 PCIe in Kubernetes in a VM, ECC and row remap values blocked, not root |

Tampered fixtures for the registry checks come in milestone 3.

## fixture.json

```json
{
  "description": "One line about the node.",
  "synthetic": true,
  "commands": {
    "nvidia-smi -q -x": {"stdout_file": "nvidia-smi-q-x.xml", "exit_code": 0},
    "dmesg": {"exit_code": 1, "stderr": "dmesg: read kernel buffer failed: Operation not permitted"},
    "uname -r": {"stdout": "5.15.0-105-generic\n"}
  },
  "files": {
    "/etc/os-release": {"text": "PRETTY_NAME=\"Ubuntu 22.04.4 LTS\"\n"},
    "/sys/class/dmi/id/sys_vendor": {"error": "permission"}
  },
  "paths": ["/.dockerenv"],
  "env": {"KUBERNETES_SERVICE_HOST": "10.96.0.1"},
  "euid": 0,
  "utc_offset_s": 0,
  "nvml_file": "nvml.json"
}
```

- A command that is not in `commands` gives "command not found".
- A file that is not in `files` does not exist.
- In `nvml.json`, a value `{"$error": "no_permission"}` makes that NVML call fail. The kinds are `missing`, `not_supported`, `no_permission` and `error`.
