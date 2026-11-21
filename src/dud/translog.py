"""Check the registry's transparency log (docs/DESIGN.md, "Transparency log").

The registry chains each log entry to the one before it with SHA-256, and
publishes the chain value of each day. dud keeps a copy of the published values
in ~/.dud/log_heads.json. If the registry changes an old entry, or removes one,
the chain values do not match any more, and a saved head shows the change.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ZERO = "0" * 64


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def leaf_of(entry_json: str) -> str:
    return sha256_hex(f"dud-log-v1:leaf:{entry_json}")


def chain_of(prev: str, leaf: str) -> str:
    return sha256_hex(f"dud-log-v1:chain:{prev}{leaf}")


def check_reading(card_id: str, reading: dict) -> str | None:
    """None if a lookup reading matches its logged fingerprint, else the problem."""
    log = reading.get("log")
    if not log:
        return "the reading has no log fingerprint"
    if sha256_hex(f"dud-log-v1:reading:{card_id}:{log['canonical']}") != log["fp"]:
        return "the fingerprint does not match the logged text"
    shown = {k: v for k, v in reading.items() if k not in ("trust", "yours", "log")}
    if json.loads(log["canonical"]) != shown:
        return "the reading is different from the logged text"
    return None


def verify(entries: list, heads: list) -> tuple:
    """Recompute the chain. Return (problems, chain value at each sequence number)."""
    problems, chains, chain = [], {0: ZERO}, ZERO
    for i, e in enumerate(entries, start=1):
        if e["seq"] != i:
            problems.append(f"entry {i} is missing (next is {e['seq']})")
            break
        leaf = leaf_of(e["entry"])
        if leaf != e["leaf"]:
            problems.append(f"entry {i}: the leaf hash is wrong")
        chain = chain_of(chain, leaf)
        if chain != e["chain"]:
            problems.append(f"entry {i}: the chain value is wrong")
        chains[i] = chain
    for h in heads:
        if h["seq"] not in chains:
            problems.append(f"head {h['day']}: entry {h['seq']} is not in the log")
        elif chains[h["seq"]] != h["chain"]:
            problems.append(f"head {h['day']}: the chain value does not match the entries")
    return problems, chains


def witness_path(home: Path) -> Path:
    return home / "log_heads.json"


def compare_witness(saved: dict, heads: list) -> list:
    """Days whose published head is different from the saved head, or no longer published."""
    now = {h["day"]: h["chain"] for h in heads}
    return [day for day, chain in sorted(saved.items()) if now.get(day) != chain]


def load_witness(home: Path) -> dict:
    try:
        return json.loads(witness_path(home).read_text())
    except (OSError, ValueError):
        return {}


def save_witness(home: Path, saved: dict, heads: list) -> Path:
    """Add new days. A saved day never changes: it is the evidence."""
    merged = dict(saved)
    for h in heads:
        merged.setdefault(h["day"], h["chain"])
    path = witness_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=1, sort_keys=True) + "\n")
    return path


def receipts(results_dir: Path) -> list:
    """Fingerprints from the registry responses of your full tests."""
    out = []
    for p in sorted(Path(results_dir).glob("*/registry_response.json")):
        try:
            resp = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if resp.get("status") == "accepted":
            out += [r["fp"] for r in resp.get("receipts", [])]
    return out
