"""Card ID hashing and removal of raw identifiers from raw output.

The hash scheme is FROZEN. Changing it breaks the link between old and new
readings of the same GPU. To change it, add a new scheme name (dud-card-v2)
and keep v1 readable.
"""
from __future__ import annotations

import hashlib
import re

HASH_SCHEME = "dud-card-v1"
MARKER_PREFIX = "dud-redacted:"

_NOT_REAL = {"", "N/A", "NA", "[N/A]", "NOT SUPPORTED", "[NOT SUPPORTED]", "UNKNOWN", "0"}


def _h(kind: str, value: str) -> str:
    return hashlib.sha256(f"{HASH_SCHEME}:{kind}:{value}".encode("utf-8")).hexdigest()


def uuid_hash(uuid: str) -> str:
    """Card ID: SHA-256 of the GPU UUID, trimmed and in lower case (GPU-xxxxxxxx-...)."""
    return _h("uuid", uuid.strip().lower())


def serial_hash(serial: str) -> str:
    """Serial ID: SHA-256 of the board serial number, trimmed and in upper case."""
    return _h("serial", serial.strip().upper())


def other_hash(tag: str, value: str) -> str:
    return _h(tag, value.strip())


def is_marker(value: str | None) -> bool:
    return value is not None and value.strip().startswith(MARKER_PREFIX)


def is_real_id(value: str | None) -> bool:
    """True when the value is a real identifier (not N/A, not empty, not already redacted)."""
    if value is None or is_marker(value):
        return False
    return value.strip().upper() not in _NOT_REAL


def marker(kind: str, digest: str) -> str:
    return f"{MARKER_PREFIX}{kind}_sha256:{digest}"


def hash_from_marker(value: str) -> str:
    return value.strip().rsplit(":", 1)[-1]


_ID_TAG = re.compile(r"<(uuid|[a-z_]*serial[a-z_]*)>([^<]*)</\1>")
_PROCESSES = re.compile(r"<(processes|accounted_processes)>(.*?)</\1>", re.S)


def redact_smi_xml(text: str) -> tuple[str, list[str]]:
    """Replace UUIDs, serial numbers and process lists in `nvidia-smi -q -x` output.

    Only the matched element text changes, so the rest of the XML stays byte for
    byte the same. Safe to run twice.
    """
    done: set[str] = set()

    def id_sub(m: re.Match) -> str:
        tag, value = m.group(1), m.group(2)
        if not is_real_id(value):
            return m.group(0)
        if tag == "uuid":
            new = marker("uuid", uuid_hash(value))
        elif tag == "serial":
            new = marker("serial", serial_hash(value))
        else:
            new = marker(tag, other_hash(tag, value))
        done.add(tag)
        return f"<{tag}>{new}</{tag}>"

    def proc_sub(m: re.Match) -> str:
        tag, body = m.group(1), m.group(2)
        if "<process_info" not in body:
            return m.group(0)
        done.add(tag)
        return f"<{tag}>{MARKER_PREFIX}removed</{tag}>"

    text = _ID_TAG.sub(id_sub, text)
    text = _PROCESSES.sub(proc_sub, text)
    return text, sorted(done)


def secrets_for(uuid: str | None, serial: str | None) -> dict[str, str]:
    """Map raw identifiers to their markers, for scrubbing any other raw output."""
    out = {}
    if is_real_id(uuid):
        out[uuid.strip()] = marker("uuid", uuid_hash(uuid))
    if is_real_id(serial):
        out[serial.strip()] = marker("serial", serial_hash(serial))
    return out
