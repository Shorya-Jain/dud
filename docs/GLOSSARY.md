# dud glossary

Use these terms in all text for users: CLI output, reports, error messages, the README and the docs.
Use each term with one meaning only.
Do not use the words in the "Do not use" column.
`tests/test_text_ste.py` checks `src/dud/text.py` against the "Do not use" column.

| Term | Meaning | Do not use |
|---|---|---|
| GPU | One NVIDIA graphics processor and its memory, as one card. | graphics card, accelerator |
| node | One computer that has 1 to 8 GPUs. | server, box, instance |
| provider | The company that rents the node to the user. | vendor, cloud, landlord |
| container | A software boundary (Docker or Kubernetes) around the processes on a node. | pod, sandbox |
| VM | A virtual machine. The provider can run the node as a VM. | virtual server, guest |
| card ID | The SHA-256 hash of the GPU UUID. It identifies one GPU in the registry. | card hash, GPU hash, fingerprint |
| serial ID | The SHA-256 hash of the GPU board serial number. | serial hash |
| UUID | The unique identifier that the driver shows for a GPU. It does not leave the node. | GUID |
| serial number | The board serial number of a GPU. It does not leave the node. | serial no |
| ECC error | An error that the GPU memory finds with its error-correcting code. | memory fault, bit flip |
| correctable ECC error | An ECC error that the GPU corrects. | single-bit error, SBE |
| uncorrectable ECC error | An ECC error that the GPU cannot correct. | double-bit error, DBE |
| volatile count | A count since the last driver load or GPU reset. | current count, session count |
| aggregate count | A count for the full life of the GPU. The GPU keeps it in its InfoROM. | lifetime count, total count |
| row remap | The replacement of a bad memory row with a spare memory row. | remapped row, row replacement, row remapping |
| pending row remap | A row remap that starts at the next GPU reset. | pending remap |
| failed row remap | A row remap that the GPU could not do, because it had no spare row. | remap failure |
| bank availability | The number of memory banks at each level of spare rows: maximum, high, partial, low and none. | bank histogram, remap histogram |
| retired page | A memory page that an older GPU stops using after ECC errors. | blacklisted page |
| XID error | An error message from the NVIDIA driver in the kernel log. | Xid event, XID event |
| kernel log | The Linux kernel message log (dmesg or journalctl). | syslog, system log |
| throttle reason | A reason that the GPU decreases its clock speed. | clock event reason, slowdown reason |
| power limit | The maximum power that the driver lets the GPU use. | power cap, TDP |
| PCIe link generation | The PCIe version that a link uses (for example 4 or 5). | PCIe speed |
| PCIe link width | The number of PCIe lanes that a link uses (for example 16x). | lane count |
| NVLink | The NVIDIA link between GPUs. | NV link |
| GPU connection | How two GPUs connect: NVLink or a PCIe path. | topology |
| value | One item that dud reads, for example a count or a version. | metric, datum |
| status | The visibility of a value: available, blocked, not supported, error or skipped. | state of value |
| available | dud read the value. | visible, present |
| blocked | The provider, the VM, the container or the permissions prevent dud from reading the value. | hidden, restricted, denied |
| not supported | The GPU, the driver or the tool does not have the value. | unavailable, N/S |
| raw output | The text that a command gives, before dud reads it. | raw data, dump |
| result file | The JSON file that dud writes for one test (result.json). | results file, output file |
| report | The Markdown file that dud writes for people to read (report.md). | summary file |
| fixture | A folder of recorded raw output. Mock mode uses it in place of a GPU. | test data, sample |
| quick test | The test that `dud quick` does. It takes approximately 1 minute. | quick check, scan |
| full test | The test that `dud full` does. It takes approximately 60 to 90 minutes. | full diagnostic, deep scan |
| verdict | The result of the grading rules: KEEP, KILL or UNKNOWN. | grade, score, rating |
| registry | The shared record of results for each card ID. | database |
| challenge | A task from the registry that proves that a GPU did the full test. | puzzle, captcha |
| nonce | A single-use random number that the registry gives for one challenge. | salt, seed value |
| token | The secret that `dud login` keeps in ~/.dud/. It identifies your account to the registry. | API key, password |
| access | The right to look up the registry. A full test gives it for 30 days. | subscription, license |
| lookup | One request for the registry data of one card ID. | query, search |
| quota | The maximum number of lookups in one day. | allowance, limit per day |
| submission | One full-test result that dud sends to the registry. | upload |
| accepted | The status of a submission that passed all checks. Its data goes into the registry. | valid result |
| flagged | The status of a submission that the registry keeps for admin review. It gives no access. | on hold, pending review |
| rejected | The status of a submission that failed a check. Its data does not go into the registry. | refused |
| contributor | An account that sent accepted submissions. | uploader, submitter |
| trust | A number from 0 to 1 for each contributor. New contributors have low trust. | reputation, karma |
| quarantine | An admin action that stops an account: no access, and its readings are not shown. | ban, suspend |
| admin | The owner of the registry. | moderator, operator |
| digest | A 32-bit number that the client makes from one challenge product. | checksum |
| Merkle root | One hash that represents all digests of one GPU in a challenge. | tree hash |
