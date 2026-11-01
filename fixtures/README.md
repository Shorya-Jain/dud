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
| `a100_sxm4_40gb_real` | **Real node.** 1x A100 SXM4 40GB on Vast.ai, driver 615, DCGM 4.7, Docker, power limit 300 W of 400 W |

To make a fixture from a real full test, run:
`.venv/bin/python scripts/fixture_from_result.py <result.json> <fixture name> "<description>"`
The raw output in a result file is already redacted.

## Tampered fixtures

`tampered/<name>/result.json` is a full-test result that the registry must not accept.
`tampered/<name>/expect.json` gives the expected status and the check that must catch it.
`server/test/api.test.ts` runs every folder in `tampered/`.
`scripts/make_server_fixtures.py` makes them. Do not edit them by hand.

| Fixture | Change | Expected |
|---|---|---|
| `edited_counters` | Parsed uncorrectable ECC count 2 changed to 0. The raw XML still shows 2. | rejected, `parsed_values` |
| `lowered_counters` | XML and parsed values both changed from 41 to 10, after an earlier reading with 41. | flagged, `counters` |
| `replayed_output` | The same raw XML as an earlier accepted submission. | rejected, `replay` |
| `wrong_memory` | An H100 SXM5 80GB with 40960 MiB, in the XML and in the parsed values. | rejected, `specs` |
| `impossible_timing` | The challenge commit 1 s after the start. The minimum is 60 s. | rejected, `challenge` |

## Other test data

- `challenge_vectors.json`: challenge results from the Python code. The server tests check that the TypeScript code gives the same results.
- `server/test/fixtures/*.json`: honest full-test results, made from the four mock fixtures.

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
