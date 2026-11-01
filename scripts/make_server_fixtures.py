#!/usr/bin/env python3
"""Make the test data that the registry server tests use.

- fixtures/challenge_vectors.json: challenge results from the Python code.
  The TypeScript server must give the same results.
- server/test/fixtures/<name>.json: full-test result files made from the mock fixtures.
- fixtures/tampered/<name>/: result files that the registry must not accept, with expect.json.

Run: .venv/bin/python scripts/make_server_fixtures.py
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dud import challenge as ch, model  # noqa: E402
from dud.collect import collect  # noqa: E402
from dud.fulltest import run_tests  # noqa: E402
from dud.probe import MockProbe  # noqa: E402

FIX = ROOT / "fixtures"
SERVER_FIX = ROOT / "server" / "test" / "fixtures"
TAMPERED = FIX / "tampered"
# Fixtures from real nodes (name ends with "_real") are not in git. They are used when they are on this computer.
FULL_FIXTURES = ["h100_sxm_healthy", "h100_sxm_pending_remap", "a100_80gb_pcie", "container_ecc_hidden"] + [
    p.name for p in sorted(FIX.iterdir()) if p.name.endswith("_real") and (p / "fixture.json").exists()]


def vectors() -> dict:
    p = {"m": 4, "n": 3, "k": 8, "pool": 2, "batch": 2}
    nonce, card = "test-nonce", "ab" * 32
    seed = ch.seed_for(nonce, card)
    digests = ch.digests_ref(seed, p, 5)
    levels = ch.merkle_levels(digests)
    return {
        "mix32": [[x, ch.mix32(x)] for x in (0, 1, 0xDEADBEEF, 0xFFFFFFFF)],
        "h": [[[seed, 3, 7], ch.h(seed, 3, 7)], [[123, 1], ch.h(123, 1)]],
        "params": p,
        "nonce": nonce,
        "card_id": card,
        "seed": seed,
        "plans": [list(ch.plan(seed, j, p)) for j in range(5)],
        "digests": digests,
        "merkle_root": levels[-1][0].hex(),
        "proof_j3": ch.merkle_proof(levels, 3),
        "product_j3": [v for row in ch.product_ref(seed, 3, p) for v in row],
        "product_j3_b64": ch.encode_product(ch.product_ref(seed, 3, p)),
    }


def smi_time(doc: dict) -> datetime:
    local = datetime.strptime(doc["host"]["smi_timestamp"]["value"], "%a %b %d %H:%M:%S %Y")
    return local.replace(tzinfo=timezone.utc) - timedelta(seconds=doc["run"]["utc_offset_s"])


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def full_doc(name: str) -> dict:
    """A full-test result, as a real node would make it. Times match the nvidia-smi time."""
    probe = MockProbe(FIX / name)
    doc = collect(probe, mode="full", options={"gpus": None, "load_minutes": 15, "skip_dcgm": False, "submit": True})
    run_tests(probe, doc, load_minutes=15, skip_dcgm=False, gpus=None, say=lambda *a: None)
    doc["run"]["mock"] = False
    doc["run"]["fixture"] = None
    doc["run"]["provider"]["reported"] = "testcloud"
    start = smi_time(doc) - timedelta(seconds=30)
    doc["run"]["started_at"] = iso(start)
    doc["run"]["finished_at"] = iso(start + timedelta(seconds=3600))
    doc["run"]["duration_s"] = 3600.0
    for e in doc["raw"]:
        e["started_at"] = iso(start + timedelta(seconds=1))
    return doc


def replace_raw(doc: dict, raw_id: str, old: str, new: str) -> None:
    """Edit a raw output and store it again with a correct hash (a careful forger)."""
    entry = next(e for e in doc["raw"] if e["id"] == raw_id)
    text = model.raw_text(entry)
    assert old in text, old
    fresh = model.RawStore().add(raw_id, entry["kind"], entry["command"], text.replace(old, new, 1),
                                 status=entry["status"], exit_code=entry["exit_code"], started_at=entry["started_at"],
                                 redactions=entry["redactions"])
    entry.update({k: fresh[k] for k in ("sha256", "bytes", "content")})


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")


def main() -> None:
    write(FIX / "challenge_vectors.json", vectors())
    docs = {name: full_doc(name) for name in FULL_FIXTURES}
    for name, doc in docs.items():
        write(SERVER_FIX / f"{name}.json", doc)

    base = docs["h100_sxm_pending_remap"]

    # Each tampered result except the replay comes from a new run, so that only its own edit can fail.
    def fresh():
        return full_doc("h100_sxm_pending_remap")

    # 1. Parsed counter edited, raw XML not edited.
    d = fresh()
    d["gpus"][0]["history"]["ecc"]["aggregate"]["uncorrectable"]["value"] = 0
    write(TAMPERED / "edited_counters" / "result.json", d)
    write(TAMPERED / "edited_counters" / "expect.json", {
        "description": "The parsed aggregate uncorrectable ECC count is 0, but the raw XML shows 2.",
        "status": "rejected", "check": "parsed_values"})

    # 2. Counters edited in the raw XML and in the parsed values, so that they agree.
    #    Only the history of the card can find it.
    d = fresh()
    replace_raw(d, "smi_q_x", "<dram_correctable>41</dram_correctable>", "<dram_correctable>10</dram_correctable>")
    d["gpus"][0]["history"]["ecc"]["aggregate"]["correctable"]["value"] = 10
    d["gpus"][0]["history"]["ecc"]["aggregate"]["detail"]["value"]["dram_correctable"] = 10
    write(TAMPERED / "lowered_counters" / "result.json", d)
    write(TAMPERED / "lowered_counters" / "expect.json", {
        "description": "A consistent edit lowers the aggregate correctable ECC count from 41 to 10 after a reading with 41.",
        "setup": ["h100_sxm_pending_remap"], "status": "flagged", "check": "counters"})

    # 3. Replay: the same raw output as an accepted submission, with a new run ID.
    d = copy.deepcopy(base)
    d["run"]["run_id"] = "00000000-0000-4000-8000-000000000001"
    write(TAMPERED / "replayed_output" / "result.json", d)
    write(TAMPERED / "replayed_output" / "expect.json", {
        "description": "The raw nvidia-smi XML is the same as in an earlier accepted submission.",
        "setup": ["h100_sxm_pending_remap"], "status": "rejected", "check": "replay"})

    # 4. Wrong memory size for the model, edited consistently in the XML and in the parsed values.
    d = fresh()
    replace_raw(d, "smi_q_x", "<total>81559 MiB</total>", "<total>40960 MiB</total>")
    d["gpus"][0]["identity"]["memory_total_mib"]["value"] = 40960
    write(TAMPERED / "wrong_memory" / "result.json", d)
    write(TAMPERED / "wrong_memory" / "expect.json", {
        "description": "An H100 SXM5 80GB that reports 40960 MiB of memory.",
        "status": "rejected", "check": "specs"})

    # 5. Impossible benchmark time: the commit arrives faster than the datasheet allows.
    write(TAMPERED / "impossible_timing" / "result.json", fresh())
    write(TAMPERED / "impossible_timing" / "expect.json", {
        "description": "The challenge commit arrives 1 s after the issue. The minimum for this work is 60 s.",
        "challenge_min_ms": 60000, "commit_after_ms": 1000, "status": "rejected", "check": "challenge",
        "commit_error": "too fast"})
    print(f"Wrote {len(docs)} server fixtures, 5 tampered fixtures and the challenge vectors.")


if __name__ == "__main__":
    main()
