"""The result document: Field values, raw output storage, save and load.

See src/dud/schema/result.v1.json for the full contract and docs/DESIGN.md
for the reasons behind it.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import SCHEMA_VERSION, __version__, ids

_GPU_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

STATUSES = ("ok", "blocked", "not_supported", "error", "skipped")
FIELD_KEYS = ("value", "status", "source", "raw_ref", "reason", "detail")


class DudError(Exception):
    """An error with a message for the user (in Simplified Technical English)."""


# --- Field: every reading carries its own visibility -------------------------

def ok(value, source: str, raw_ref: str | None = None, reason: str | None = None) -> dict:
    return {"value": value, "status": "ok", "source": source, "raw_ref": raw_ref,
            "reason": reason, "detail": None}


def missing(status: str, source: str, reason: str, detail=None, raw_ref: str | None = None) -> dict:
    assert status in STATUSES and status != "ok", status
    if detail is not None:
        detail = str(detail).strip()[:500] or None
    return {"value": None, "status": status, "source": source, "raw_ref": raw_ref,
            "reason": reason, "detail": detail}


def is_field(obj) -> bool:
    return isinstance(obj, dict) and len(obj) == len(FIELD_KEYS) and all(k in obj for k in FIELD_KEYS)


def iter_fields(obj, path: str = ""):
    """Yield (dotted path, field) for every Field inside obj."""
    if is_field(obj):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from iter_fields(value, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from iter_fields(value, f"{path}[{i}]")


def get_path(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def set_path(obj, path: str, value) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        obj = obj[part]
    obj[parts[-1]] = value


def visibility_counts(obj) -> dict:
    counts = {s: 0 for s in STATUSES}
    for _, f in iter_fields(obj):
        counts[f["status"]] += 1
    return counts


# --- Raw output --------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_text(entry: dict) -> str:
    return gzip.decompress(base64.b64decode(entry["content"])).decode("utf-8")


class RawStore:
    """Collects raw outputs. Removes every known raw identifier before storage."""

    def __init__(self, secrets: dict[str, str] | None = None):
        self.entries: list[dict] = []
        self.secrets = secrets or {}

    def scrub(self, text: str) -> str:
        for raw, mark in self.secrets.items():
            text = text.replace(raw, mark)
        # Safety net: any other GPU UUID in any tool output.
        return _GPU_UUID.sub(lambda m: ids.marker("uuid", ids.uuid_hash(m.group(0))), text)

    def add(self, raw_id: str, kind: str, command: list[str], text: str, *, status: str = "ok",
            exit_code: int | None = None, started_at: str | None = None, duration_ms: int = 0,
            redactions=(), stderr: str | None = None, gpu_index: int | None = None) -> dict:
        text = self.scrub(text or "")
        data = text.encode("utf-8")
        entry = {
            "id": raw_id,
            "kind": kind,
            "command": list(command),
            "gpu_index": gpu_index,
            "status": status,
            "exit_code": exit_code,
            "started_at": started_at or utc_now(),
            "duration_ms": int(duration_ms),
            "redactions": sorted(redactions),
            "stderr": self.scrub(stderr.strip())[:4000] if stderr and stderr.strip() else None,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "encoding": "gzip+base64",
            # mtime=0 keeps the compressed bytes the same for the same text.
            "content": base64.b64encode(gzip.compress(data, mtime=0)).decode("ascii"),
        }
        self.entries.append(entry)
        return entry

    def add_result(self, raw_id: str, result, text: str | None = None, redactions=()) -> dict:
        """Add the output of a command (a probe.CmdResult)."""
        status = "ok" if result.ok else ("blocked" if result.failure == "permission" else "error")
        return self.add(raw_id, "command", result.argv, result.stdout if text is None else text,
                        status=status, exit_code=result.exit_code, started_at=result.started_at,
                        duration_ms=result.duration_ms, redactions=redactions, stderr=result.stderr)


# --- Document ----------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_doc(*, mode: str, started_at: str, finished_at: str, duration_s: float, utc_offset_s: int | None,
            provider: str | None, options: dict, mock: bool, fixture: str | None, host: dict,
            gpus: list, node: dict, findings: list, raw: list) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dud.result",
        "run": {
            "run_id": str(uuid.uuid4()),
            "mode": mode,
            "dud_version": __version__,
            "mock": mock,
            "fixture": fixture,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_s": duration_s,
            "utc_offset_s": utc_offset_s,
            "options": options,
            "provider": {"reported": provider},
        },
        "host": host,
        "gpus": gpus,
        "node": node,
        "findings": findings,
        "challenge": None,
        "attestation": None,
        "raw": raw,
    }


def save_result(doc: dict, out_dir: Path, report_text: str) -> Path:
    """Write result.json, report.md and raw/<id>.txt into a new folder. Return the folder."""
    stamp = doc["run"]["started_at"][:19].replace("-", "").replace(":", "")
    folder = Path(out_dir) / f"{doc['run']['mode']}-{stamp}Z-{doc['run']['run_id'][:6]}"
    (folder / "raw").mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (folder / "report.md").write_text(report_text, encoding="utf-8")
    for entry in doc["raw"]:
        (folder / "raw" / f"{entry['id']}.txt").write_text(raw_text(entry), encoding="utf-8")
    return folder


def load_result(path: Path) -> dict:
    from . import text as T

    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DudError(T.BAD_RESULT_FILE.format(path=path))
    if not isinstance(doc, dict) or doc.get("kind") != "dud.result":
        raise DudError(T.NOT_A_RESULT_FILE.format(path=path))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise DudError(T.WRONG_SCHEMA_VERSION.format(found=doc.get("schema_version"), expected=SCHEMA_VERSION))
    return doc
