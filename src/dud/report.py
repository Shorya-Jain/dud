"""Render a result document as a Markdown report and as a short terminal summary."""
from __future__ import annotations

from . import text as T
from .model import STATUSES, get_path, iter_fields, visibility_counts

HOST_ROWS = [
    ("driver_version", None), ("cuda_driver_version", None), ("nvml_version", None),
    ("attached_gpus", None), ("os", None), ("kernel", None), ("cpu_model", None),
    ("environment.container", None), ("environment.virtualization", None),
    ("environment.dmi_vendor", None), ("environment.dmi_product", None),
    ("environment.is_root", None), ("kernel_log", None),
]
IDENTITY_ROWS = [
    ("identity.name", None), ("identity.model_key", None), ("identity.form_factor", None),
    ("card.uuid_sha256", "id"), ("card.serial_sha256", "id"),
    ("identity.architecture", None), ("identity.vbios", None), ("identity.board_part_number", None),
    ("identity.pci_device_id", None), ("identity.pci_subsystem_id", None),
    ("identity.inforom_image", None), ("identity.gsp_firmware", None),
    ("identity.memory_total_mib", "MiB"),
    ("identity.power_limit_default_w", "W"), ("identity.power_limit_current_w", "W"),
    ("identity.power_limit_max_w", "W"),
    ("identity.pcie.gen_max", None), ("identity.pcie.gen_current", None),
    ("identity.pcie.width_max", "x"), ("identity.pcie.width_current", "x"),
    ("identity.nvlink", "nvlink"), ("identity.fabric_state", None),
    ("identity.mig_mode", None), ("identity.persistence_mode", None), ("identity.compute_mode", None),
    ("identity.max_clocks.sm_mhz", "MHz"), ("identity.max_clocks.mem_mhz", "MHz"),
]
HISTORY_ROWS = [
    ("history.ecc_mode", None), ("history.ecc_mode_pending", None),
    ("history.ecc.volatile.correctable", None), ("history.ecc.volatile.uncorrectable", None),
    ("history.ecc.aggregate.correctable", None), ("history.ecc.aggregate.uncorrectable", None),
    ("history.row_remap.correctable", None), ("history.row_remap.uncorrectable", None),
    ("history.row_remap.pending", None), ("history.row_remap.failed", None),
    ("history.row_remap.bank_availability.max", None), ("history.row_remap.bank_availability.high", None),
    ("history.row_remap.bank_availability.partial", None), ("history.row_remap.bank_availability.low", None),
    ("history.row_remap.bank_availability.none", None),
    ("history.retired_pages.correctable", None), ("history.retired_pages.uncorrectable", None),
    ("history.retired_pages.pending", None),
    ("history.ecc.volatile.detail", "dict"), ("history.ecc.aggregate.detail", "dict"),
    ("history.ecc.aggregate_sram_sources", "dict"),
]
SNAPSHOT_ROWS = [
    ("snapshot.gpu_temp_c", "C"), ("snapshot.memory_temp_c", "C"), ("snapshot.power_draw_w", "W"),
    ("snapshot.performance_state", None), ("snapshot.reset_required", None),
    ("snapshot.pcie_replay_count", None), ("snapshot.throttle_reasons_active", "list"),
]


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows) -> str:
    lines = ["| " + " | ".join(_cell(h) for h in headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def fmt_value(v, unit=None) -> str:
    if isinstance(v, bool):
        return T.YES if v else T.NO
    if v is None:
        return T.DASH
    if unit == "id":
        return f"`{v[:16]}`"
    if unit == "nvlink":
        return T.NVLINK_VALUE.format(**v)
    if unit == "list":
        return ", ".join(v) if v else T.NONE
    if unit == "dict":
        return ", ".join(f"{k}={fmt_value(x)}" for k, x in v.items())
    if isinstance(v, float):
        v = f"{v:g}"
    return f"{v} {unit}" if unit and unit != "x" else (f"{v}x" if unit == "x" else str(v))


def fmt_field(f, unit=None) -> str:
    if f is None or f["status"] != "ok":
        return T.DASH
    return fmt_value(f["value"], unit)


def fmt_status(f) -> str:
    if f["status"] == "ok" and f["reason"] == "from_nvml":
        return T.STATUS_FROM_NVML
    return T.STATUS[f["status"]]


def _rows(obj, rows) -> str:
    out = []
    for path, unit in rows:
        f = get_path(obj, path)
        if f is None:
            continue
        out.append((T.LABELS.get(path, path), fmt_field(f, unit), fmt_status(f)))
    return _table([T.COL_ITEM, T.COL_VALUE, T.COL_STATUS], out)


def _not_read(obj) -> list:
    """One line per (status, reason, detail), with the labels of all values that share it."""
    groups = {}
    for path, f in iter_fields(obj):
        if f["status"] != "ok":
            groups.setdefault((f["status"], f["reason"], f["detail"]), []).append(T.LABELS.get(path, path))
    lines = []
    for (status, reason, detail), labels in groups.items():
        line = f"- **{T.STATUS[status]}**: {', '.join(labels)}. {T.REASONS.get(reason, T.REASON_UNKNOWN)}"
        if detail:
            line += " " + T.DETAIL.format(detail=detail.replace("`", "'"))
        lines.append(line)
    return lines


def _findings(findings: list) -> list:
    out = []
    for item in findings:
        template = T.FINDINGS.get(item["code"], T.FINDING_UNKNOWN)
        line = "- " + template.format(code=item["code"], label=T.LABELS.get(item.get("path") or "", item.get("path")))
        if item.get("detail"):
            line += " " + T.DETAIL.format(detail=item["detail"])
        out.append(line)
    return out


def _connections(host: dict) -> str:
    f = host["topology"]
    if f["status"] != "ok":
        return T.CONNECTIONS_NOT_READ + "\n"
    rows = f["value"]["rows"]
    gpus = [c for c in f["value"]["columns"] if c.startswith("GPU") and c in rows]
    table = _table([""] + gpus, [[g] + [rows[g].get(c, "") for c in gpus] for g in gpus])
    return table + "\n" + T.CONNECTIONS_LEGEND + "\n"


def _duration(seconds: float) -> str:
    return T.DURATION.format(minutes=int(seconds // 60), seconds=int(round(seconds % 60)))


def render(doc: dict) -> str:
    run, host = doc["run"], doc["host"]
    out = [f"# {T.REPORT_TITLE}\n"]
    if run["mock"]:
        out.append(f"> {T.MOCK_BANNER}\n")

    out.append(f"## {T.SECTION_TEST}\n")
    run_rows = [
        (T.RUN_LABELS["mode"], T.MODES.get(run["mode"], run["mode"])),
        (T.RUN_LABELS["dud_version"], run["dud_version"]),
        (T.RUN_LABELS["started_at"], run["started_at"]),
        (T.RUN_LABELS["duration"], _duration(run["duration_s"])),
        (T.RUN_LABELS["provider"], run["provider"]["reported"] or T.NOT_GIVEN),
    ]
    if run["mock"]:
        run_rows.append((T.RUN_LABELS["fixture"], run["fixture"]))
    out.append(_table([T.COL_ITEM, T.COL_VALUE], run_rows))

    out.append(f"## {T.SECTION_VERDICT}\n")
    out.append((T.NO_VERDICT if doc["node"]["verdict"] is None else str(doc["node"]["verdict"])) + "\n")

    out.append(f"## {T.SECTION_NODE}\n")
    attached = host["attached_gpus"]["value"] if host["attached_gpus"]["status"] == "ok" else doc["node"]["gpu_count"]
    out.append(T.NODE_SUMMARY.format(attached=attached, examined=len(doc["gpus"])) + "\n")
    out.append(_rows(host, HOST_ROWS))
    out.append(f"### {T.SECTION_CONNECTIONS}\n")
    out.append(_connections(host))
    host_missing = _not_read(host)
    if host_missing:
        out.append(f"### {T.SECTION_NOT_READ}\n")
        out.append("\n".join(host_missing) + "\n")
    if doc["findings"]:
        out.append(f"### {T.SECTION_FINDINGS}\n")
        out.append("\n".join(_findings(doc["findings"])) + "\n")

    for gpu in doc["gpus"]:
        name = gpu["identity"]["name"]["value"] or T.DASH
        out.append(f"## GPU {gpu['index']}: {name}\n")
        out.append(T.CARD_ID_NOTE + "\n")
        out.append(f"### {T.SECTION_IDENTITY}\n")
        out.append(_rows(gpu, IDENTITY_ROWS))
        out.append(f"### {T.SECTION_HISTORY}\n")
        out.append(_rows(gpu, HISTORY_ROWS))
        out.append(f"### {T.SECTION_XID}\n")
        xid = gpu["history"]["xid_events"]
        if xid["status"] != "ok":
            out.append(T.XID_NOT_READ + "\n")
        elif not xid["value"]:
            out.append(T.NO_XID + "\n")
        else:
            out.append(_table([T.COL_XID, T.COL_UPTIME, T.COL_MESSAGE],
                              [(e["xid"], fmt_value(e["uptime_s"]), e["message"]) for e in xid["value"]]))
        out.append(f"### {T.SECTION_SNAPSHOT}\n")
        out.append(_rows(gpu, SNAPSHOT_ROWS))
        out.append(f"### {T.SECTION_NOT_READ}\n")
        lines = _not_read(gpu)
        out.append(("\n".join(lines) if lines else T.ALL_READ) + "\n")
        if gpu["findings"]:
            out.append(f"### {T.SECTION_FINDINGS}\n")
            out.append("\n".join(_findings(gpu["findings"])) + "\n")

    out.append(f"## {T.SECTION_VISIBILITY}\n")
    out.append(T.VISIBILITY_INTRO + "\n")
    scopes = [(T.SCOPE_NODE, host)] + [(T.SCOPE_GPU.format(index=g["index"]), g) for g in doc["gpus"]]
    rows = []
    for label, obj in scopes:
        counts = visibility_counts(obj)
        rows.append([label] + [counts[s] for s in STATUSES])
    out.append(_table([T.COL_SCOPE] + [T.STATUS[s] for s in STATUSES], rows))
    return "\n".join(out)


def terminal_summary(doc: dict) -> str:
    def cell(f) -> str:
        return fmt_field(f) if f["status"] == "ok" else T.STATUS[f["status"]]

    rows = [T.SUMMARY_HEADERS]
    for gpu in doc["gpus"]:
        blocked = sum(1 for _, f in iter_fields(gpu) if f["status"] == "blocked")
        card = gpu["card"]["uuid_sha256"]
        rows.append((
            str(gpu["index"]),
            cell(gpu["identity"]["name"]),
            card["value"][:16] if card["status"] == "ok" else T.STATUS[card["status"]],
            cell(gpu["history"]["ecc"]["volatile"]["uncorrectable"]),
            cell(gpu["history"]["row_remap"]["pending"]),
            str(blocked),
        ))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)
