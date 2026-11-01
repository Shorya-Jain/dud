"""All user-facing text.

Write in ASD-STE100 Simplified Technical English:
- Use the terms in docs/GLOSSARY.md. Do not use the words in its "Do not use" column.
- One instruction per sentence. Use the imperative for instructions. Use the active voice.
- Keep each sentence to 20 words or fewer. tests/test_text_ste.py checks this.
"""

# --- CLI ---------------------------------------------------------------------

MOCK_BANNER = "MOCK MODE: dud uses fixture data. These results are not from a real GPU."
QUICK_START = "dud {version}: quick test started."
FULL_START = "dud {version}: full test started."
DCGM_START = "DCGM: dud runs the level 3 diagnostic. This can take up to 30 minutes."
DCGM_DONE = "DCGM: the diagnostic is complete."
PERF_GPU = "Performance: dud tests GPU {index}."
PERF_P2P = "Performance: dud tests the bandwidth between each pair of GPUs."
LOAD_START = "Load test: dud runs a sustained load for {minutes} minutes. Number of GPUs: {count}."
VERDICT_LINE = "Verdict: {verdict}. {summary}"
GPU_VERDICT_LINE = "GPU {index}: {verdict}. {summary}"
VERDICT_ALL_PASSED = "All checks passed."
NODE_KEEP = "All GPUs passed the checks."
NODE_KILL = "Do not use GPU {gpus}. See the report for the reasons."
NODE_UNKNOWN = "dud cannot give a verdict for GPU {gpus}, because it cannot read key values."
REGISTRY_KILL = "The registry has a KILL verdict for this GPU from {date}. Ask the provider for a different GPU."
REGISTRY_RECENT_KEEP = "A full test {when} gave KEEP. The error counts did not go up after it. Start your work."
REGISTRY_KEEP_COUNTS_UP = "A full test {when} gave KEEP, but error counts went up after it. Run dud full to examine the GPU again."
REGISTRY_KEEP_BUT_UNKNOWN = "A full test {when} gave KEEP."
WHEN_TODAY = "today"
WHEN_ONE_DAY = "1 day ago"
WHEN_DAYS = "{days} days ago"
STOPPED = "dud stopped."
BAD_LOAD_MINUTES = "The --load-minutes value must be 1 or more."
RESULT_WRITTEN = "Result file: {path}"
REPORT_WRITTEN = "Report: {path}"
RAW_WRITTEN = "Raw output: {path}"
NO_GPUS = "dud found no GPUs. Make sure that the NVIDIA driver is installed and that nvidia-smi operates."
GPU_NOT_FOUND = "GPU {missing} is not on this node. Use GPU numbers from this list: {available}."
BAD_GPUS_FLAG = "The --gpus value is not correct. Use GPU numbers with commas between them, for example 0,1."
FIXTURE_NOT_FOUND = "dud cannot find the fixture '{name}'. Set DUD_FIXTURE to a fixture name or to a fixture folder."
BAD_RESULT_FILE = "dud cannot read the file {path}. Make sure that the path is correct."
NOT_A_RESULT_FILE = "The file {path} is not a dud result file."
WRONG_SCHEMA_VERSION = "This result file uses schema version {found}. This version of dud reads schema version {expected}."

# Login and account
LOGIN_OPEN = "On a computer or phone with a browser, open {uri}."
LOGIN_CODE = "Type this code: {code}"
LOGIN_WAIT = "dud waits while you approve the sign-in on GitHub."
LOGIN_DONE = "You are signed in as {login}. dud keeps your token in {path}."
LOGIN_NEW_ACCOUNT = "Your GitHub account is new. The registry keeps your first results for review before they give access."
LOGOUT_DONE = "dud deleted your token from this computer."
LOGOUT_NONE = "dud did not find a token on this computer."
NOT_LOGGED_IN = "You are not signed in. Run dud login."
STATUS_ACCOUNT = "Signed in as {login} at {url}."
STATUS_ACCESS = "You have registry access until {date}."
STATUS_NO_ACCESS = "You do not have registry access. Run dud full to get access."
STATUS_LOOKUPS = "Lookups today: {used} of {quota}."
STATUS_QUARANTINED = "The registry owner stopped this account. Your results do not go into the registry."
GITHUB_DEVICE_FAILED = "GitHub did not start the sign-in. Details: {detail}"
GITHUB_DENIED = "You did not approve the sign-in on GitHub."
GITHUB_EXPIRED = "The sign-in code expired. Run dud login again."
REGISTRY_UNREACHABLE = "dud cannot connect to the registry at {url}. Details: {detail}"
REGISTRY_ERROR = "The registry sent an error (HTTP {status})."

# Full test and challenge
CARD_ID_MISSING = "GPU {index} has no card ID or no known model. The registry cannot accept a result from this node."
TORCH_MISSING = "The full test needs PyTorch with CUDA. The install command is: {command}"
TORCH_ASK = "Install PyTorch now? It is a download of approximately 2.5 GB. [y/N] "
TORCH_NOT_INSTALLED = "dud stopped, because PyTorch is not installed. Install PyTorch, then run dud full again."
TORCH_NO_CUDA = "PyTorch cannot find a CUDA GPU. The full test needs a CUDA GPU."
DCGM_MISSING = "DCGM is not installed on this node. dud can install it."
DCGM_ASK = "Install DCGM ({package}) now? It is a download of up to 1 GB. [Y/n] "
DCGM_INSTALL_START = "dud installs {package} with apt. This can take some minutes."
DCGM_INSTALL_DONE = "DCGM is installed."
DCGM_INSTALL_FAILED = "dud cannot install DCGM. Details: {detail}"
DCGM_INSTALL_SEE_OUTPUT = "see the apt output above."
DCGM_INSTALL_NO_APT = "dud can install DCGM only on Linux nodes that have apt."
DCGM_INSTALL_OS = "dud can install DCGM only on Ubuntu and Debian. This node has {os}."
DCGM_INSTALL_ARCH = "dud cannot install DCGM for this CPU type: {arch}."
DCGM_INSTALL_NO_CUDA = "dud cannot read the CUDA version of the driver. It needs this version to select the DCGM package."
DCGM_INSTALL_NOT_ROOT = "To install DCGM, run dud as root or install sudo."
DCGM_INSTALL_NO_TERMINAL = "dud cannot ask about the DCGM install, because there is no terminal. Use --install-dcgm."
SELF_TEST_FAILED = "GPU {index} gave a wrong result in the challenge self-test. dud stopped. Do not use this GPU."
CHALLENGE_START = "Challenge: dud does registry work on the GPUs. Number of GPUs: {count}. Do not stop dud."
CHALLENGE_DONE = "Challenge: the registry accepted the work. The registry measured {seconds} s."
SUBMIT_START = "dud sends the result to the registry."
SUBMIT_ACCEPTED_ACCESS = "The registry accepted your result. You have registry access until {date}."
SUBMIT_ACCEPTED_NO_ACCESS = "The registry accepted your result. It does not give access. Reason: {reason}."
SUBMIT_FLAGGED = "The registry keeps your result for review. It does not give access now. Reasons: {reason}"
SUBMIT_REJECTED = "The registry did not accept your result. Reasons: {reason}"
SUBMIT_SKIPPED = "dud did not send the result, because you used --no-submit."
SUBMIT_FAILED = "dud could not send the result. Your result file is on this node. Details: {detail}"

# Registry history in the quick test
REGISTRY_NOT_LOGGED_IN = "dud did not compare with the registry. Run dud login to compare with earlier readings."
REGISTRY_CARD_NONE = "GPU {index}: the registry has no earlier readings of this GPU."
REGISTRY_CARD_HISTORY = "GPU {index}: earlier readings in the registry: {count}. Accounts: {contributors}. First reading: {first}."
REGISTRY_LOW_TRUST = "Readings with low trust come from new contributors."

HELP = {
    "description": "Check the health of a rented NVIDIA data center GPU.",
    "quick": "Read the identity and history of each GPU. This takes approximately 1 minute.",
    "full": "Do the full test and send the result to the registry.",
    "login": "Sign in with your GitHub account.",
    "logout": "Delete your registry token from this computer.",
    "status": "Show your registry account and access.",
    "offline": "Do not compare with the registry.",
    "report": "Show the report for a saved result file.",
    "report_file": "The result file (result.json).",
    "report_out": "Write the report to this file.",
    "provider": "The name of the provider that rents you this node, for example vast.ai.",
    "gpus": "Examine only these GPUs, for example 0,1. Default: all GPUs.",
    "out_dir": "Write results into this folder. Default: ./dud-results.",
    "no_submit": "Do not send the result to the registry.",
    "skip_dcgm": "Do not run the DCGM test.",
    "install_dcgm": "If DCGM is not installed, install it. Do not ask.",
    "load_minutes": "Run the load test for this number of minutes. Default: 15.",
}

SUMMARY_HEADERS = ("Verdict", "GPU", "Model", "Card ID", "Uncorrectable ECC (volatile)", "Pending row remap", "Blocked values")

# --- Report ------------------------------------------------------------------

REPORT_TITLE = "dud report"
SECTION_TEST = "Test"
SECTION_VERDICT = "Verdict"
SECTION_NODE = "Node"
SECTION_CONNECTIONS = "GPU connections"
SECTION_IDENTITY = "Identity"
SECTION_HISTORY = "History"
SECTION_SNAPSHOT = "State at test start"
SECTION_XID = "XID errors"
SECTION_NOT_READ = "Values that dud could not read"
SECTION_FINDINGS = "Findings"
SECTION_VISIBILITY = "Visibility summary"
SECTION_PERF = "Performance"
SECTION_DIAG = "DCGM diagnostic and errors during the test"
SECTION_P2P = "GPU-to-GPU bandwidth"
SECTION_CHECKS = "Grading checks"
COL_RULE = "Check"
COL_RESULT = "Result"
COL_SPEC = "Datasheet"
COL_FRACTION = "Fraction of datasheet"
COL_TEST = "Test"
COL_INFO = "Details"
RESULTS = {"pass": "Pass", "fail": "Fail", "missing": "No value", "skipped": "Skipped", "warn": "Warning",
           "skip": "Skipped", "unknown": "Unknown"}
NO_DCGM_TESTS = "The DCGM diagnostic did not run for this GPU."
P2P_NOTE = "Each cell is the copy bandwidth in GB/s from the row GPU to the column GPU."
SECTION_REGISTRY = "Registry history"
COL_DATE = "Date"
COL_PROVIDER = "Provider"
COL_TRUST = "Trust"

NO_VERDICT = "This version of dud does not give a verdict."
NODE_SUMMARY = "This node has {attached} GPUs. dud examined {examined} GPUs."
CONNECTIONS_LEGEND = "NV followed by a number means NVLink with that number of links. SYS, NODE, PHB, PXB and PIX are PCIe paths."
CONNECTIONS_NOT_READ = "dud could not read the GPU connections."
CARD_ID_NOTE = "The card ID is the SHA-256 hash of the GPU UUID. The raw UUID and serial number do not leave this node."
NO_XID = "The kernel log shows no XID errors for this GPU."
XID_NOT_READ = "dud could not read the kernel log. XID errors for this GPU are unknown."
ALL_READ = "dud read all values for this GPU."
VISIBILITY_INTRO = "Each value has a status. A blocked value is a finding about the provider."
DETAIL = "Details: `{detail}`"

COL_ITEM = "Item"
COL_VALUE = "Value"
COL_STATUS = "Status"
COL_SCOPE = "Scope"
COL_XID = "XID"
COL_UPTIME = "Kernel time (s)"
COL_MESSAGE = "Message"
SCOPE_NODE = "Node"
SCOPE_GPU = "GPU {index}"

RUN_LABELS = {
    "mode": "Test type",
    "dud_version": "dud version",
    "started_at": "Start time (UTC)",
    "duration": "Duration",
    "provider": "Provider (from the user)",
    "fixture": "Fixture",
}
MODES = {"quick": "Quick test", "full": "Full test"}
NOT_GIVEN = "Not given"
DURATION = "{minutes} min {seconds} s"

YES = "Yes"
NO = "No"
NONE = "None"
DASH = "-"
NVLINK_VALUE = "{links_active} of {links_total} links are active"

STATUS = {
    "ok": "Available",
    "blocked": "Blocked",
    "not_supported": "Not supported",
    "error": "Error",
    "skipped": "Skipped",
}
STATUS_FROM_NVML = "Available (from NVML)"

# Why a value has its status. Keys are the reason codes in the result file.
REASONS = {
    "not_in_output": "The nvidia-smi output does not include this value.",
    "smi_na": "nvidia-smi shows N/A for this value.",
    "smi_not_supported": "nvidia-smi shows that this GPU does not support this value.",
    "smi_insufficient_permissions": "nvidia-smi does not have permission to read this value.",
    "smi_error": "nvidia-smi shows an error for this value.",
    "parse_failed": "dud cannot read the format of this value.",
    "hidden_on_supported_model": "This GPU model records this value. nvidia-smi shows N/A, so the provider, VM or container blocks it.",
    "ecc_disabled": "ECC mode is disabled on this GPU. The GPU does not record ECC errors or row remaps.",
    "replaced_by_row_remap": "This GPU model uses row remaps, not retired pages.",
    "unknown_model": "dud does not know this GPU model.",
    "command_not_found": "The command is not installed on this node.",
    "command_failed": "The command stopped with an error.",
    "command_timeout": "The command did not stop in the time limit.",
    "permission_denied": "The system does not give dud permission to read this value.",
    "file_not_found": "The file for this value is not on this node.",
    "file_empty": "The file for this value is empty.",
    "kernel_log_empty": "The kernel log is empty, or this node does not keep a kernel log.",
    "nvml_missing": "dud cannot load NVML. Install the nvidia-ml-py package and the NVIDIA driver.",
    "nvml_not_supported": "NVML shows that this GPU does not support this value.",
    "nvml_no_permission": "NVML does not have permission to read this value.",
    "nvml_error": "NVML shows an error for this value.",
    "gpu_not_in_nvml": "NVML does not show this GPU.",
    "from_nvml": "nvidia-smi does not show this value. dud read it from NVML.",
    "dcgm_not_installed": "DCGM is not installed on this node. Install DCGM to run the diagnostic.",
    "dcgm_skipped_by_user": "You used --skip-dcgm.",
    "bench_not_supported": "This GPU or this PyTorch version cannot do this test.",
    "bench_failed": "The test stopped with an error.",
    "single_gpu": "This node has one GPU, so there is no GPU-to-GPU bandwidth.",
    "load_not_run": "dud did not run the load test.",
    "torch_missing": "PyTorch with CUDA is not installed, so dud did not run the performance tests.",
    "no_before_after": "dud could not read the value before and after the test.",
}
REASON_UNKNOWN = "dud has no explanation for this status."

FINDINGS = {
    "smi_nvml_mismatch": "nvidia-smi and NVML show different values for '{label}'.",
    "duplicate_card_id": "Two GPUs have the same card ID.",
    "no_gpus": "dud found no GPUs.",
    "counter_lower_than_registry": "'{label}' is lower now than in an earlier registry reading. A reset or a wrong reading can cause this.",
}
FINDING_UNKNOWN = "dud recorded the finding '{code}'."

# Labels for each value. Keys are paths inside a GPU entry or inside "host".
LABELS = {
    "card.uuid_sha256": "Card ID",
    "card.serial_sha256": "Serial ID",
    "identity.name": "Model name",
    "identity.model_key": "dud model key",
    "identity.form_factor": "Form factor",
    "identity.architecture": "Architecture",
    "identity.vbios": "VBIOS version",
    "identity.board_part_number": "Board part number",
    "identity.pci_device_id": "PCI device ID",
    "identity.pci_subsystem_id": "PCI subsystem ID",
    "identity.inforom_image": "InfoROM image version",
    "identity.gsp_firmware": "GSP firmware version",
    "identity.memory_total_mib": "Total memory",
    "identity.power_limit_default_w": "Default power limit",
    "identity.power_limit_current_w": "Current power limit",
    "identity.power_limit_max_w": "Maximum power limit",
    "identity.pcie.gen_max": "Maximum PCIe link generation",
    "identity.pcie.gen_current": "Current PCIe link generation",
    "identity.pcie.width_max": "Maximum PCIe link width",
    "identity.pcie.width_current": "Current PCIe link width",
    "identity.nvlink": "NVLink",
    "identity.mig_mode": "MIG mode",
    "identity.persistence_mode": "Persistence mode",
    "identity.compute_mode": "Compute mode",
    "identity.max_clocks.sm_mhz": "Maximum SM clock",
    "identity.max_clocks.mem_mhz": "Maximum memory clock",
    "identity.fabric_state": "NVLink fabric state",
    "history.ecc_mode": "ECC mode",
    "history.ecc_mode_pending": "ECC mode after the next GPU reset",
    "history.ecc.volatile.correctable": "Correctable ECC errors (volatile count)",
    "history.ecc.volatile.uncorrectable": "Uncorrectable ECC errors (volatile count)",
    "history.ecc.volatile.detail": "ECC error details (volatile count)",
    "history.ecc.aggregate.correctable": "Correctable ECC errors (aggregate count)",
    "history.ecc.aggregate.uncorrectable": "Uncorrectable ECC errors (aggregate count)",
    "history.ecc.aggregate.detail": "ECC error details (aggregate count)",
    "history.ecc.aggregate_sram_sources": "SRAM sources of uncorrectable ECC errors (aggregate count)",
    "history.row_remap.correctable": "Row remaps for correctable errors",
    "history.row_remap.uncorrectable": "Row remaps for uncorrectable errors",
    "history.row_remap.pending": "Pending row remap",
    "history.row_remap.failed": "Failed row remap",
    "history.row_remap.bank_availability.max": "Bank availability: maximum",
    "history.row_remap.bank_availability.high": "Bank availability: high",
    "history.row_remap.bank_availability.partial": "Bank availability: partial",
    "history.row_remap.bank_availability.low": "Bank availability: low",
    "history.row_remap.bank_availability.none": "Bank availability: none",
    "history.retired_pages.correctable": "Retired pages (multiple correctable errors)",
    "history.retired_pages.uncorrectable": "Retired pages (uncorrectable errors)",
    "history.retired_pages.pending": "Pending retired page",
    "history.xid_events": "XID errors",
    "snapshot.gpu_temp_c": "GPU temperature",
    "snapshot.memory_temp_c": "Memory temperature",
    "snapshot.power_draw_w": "Power draw",
    "snapshot.performance_state": "Performance state",
    "snapshot.reset_required": "GPU reset required",
    "snapshot.pcie_replay_count": "PCIe replay count",
    "snapshot.throttle_reasons_active": "Active throttle reasons",
    "perf.bf16_tflops": "BF16 matrix multiply",
    "perf.fp8_tflops": "FP8 matrix multiply",
    "perf.hbm_gbps": "Memory bandwidth",
    "perf.sustained_bf16_tflops": "Sustained BF16 (load test median)",
    "perf.throttle_hw_fraction": "Time with thermal or hardware slowdown",
    "perf.power_capped_fraction": "Time at the power limit",
    "perf.max_temp_c": "Maximum temperature in the load test",
    "diag.dcgm_result": "DCGM diagnostic result",
    "diag.dcgm": "DCGM diagnostic tests",
    "diag.ecc_uncorrectable_delta": "New uncorrectable ECC errors during the test",
    "diag.ecc_correctable_delta": "New correctable ECC errors during the test",
    "diag.row_remap_pending_after": "Pending row remap after the test",
    "p2p_bandwidth": "GPU-to-GPU bandwidth",
    "driver_version": "Driver version",
    "cuda_driver_version": "CUDA version (driver)",
    "nvml_version": "NVML version",
    "smi_timestamp": "nvidia-smi time",
    "attached_gpus": "GPUs on this node",
    "os": "Operating system",
    "kernel": "Linux kernel",
    "cpu_model": "CPU model",
    "environment.container": "Container",
    "environment.virtualization": "VM type",
    "environment.dmi_vendor": "System manufacturer",
    "environment.dmi_product": "System product name",
    "environment.is_root": "Root user",
    "kernel_log": "Kernel log",
    "topology": "GPU connections",
}
