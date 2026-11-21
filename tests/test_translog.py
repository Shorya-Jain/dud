"""The transparency log checks in dud log and dud quick."""
import json

from dud import translog

# The same values are in server/test/log.test.ts. The client and the server must agree.
VECTOR_ENTRIES = ['{"v":1,"type":"reading","fp":"aa"}', '{"v":1,"type":"account","account":"bb","status":"quarantined"}']
VECTOR_CHAIN = "d16a8c495fb37e293f1de54b679e23db8d80600a7e4cdf4f5f0dd81505e67484"


def make_log(texts):
    entries, chain = [], translog.ZERO
    for i, t in enumerate(texts, start=1):
        leaf = translog.leaf_of(t)
        chain = translog.chain_of(chain, leaf)
        entries.append({"seq": i, "entry": t, "leaf": leaf, "chain": chain})
    return entries


def test_vector():
    assert make_log(VECTOR_ENTRIES)[-1]["chain"] == VECTOR_CHAIN


def test_correct_log_has_no_problems():
    entries = make_log(VECTOR_ENTRIES + ['{"v":1,"type":"reading","fp":"cc"}'])
    heads = [{"day": "2026-11-01", "seq": 2, "chain": entries[1]["chain"]}, {"day": "2026-11-02", "seq": 3, "chain": entries[2]["chain"]}]
    problems, chains = translog.verify(entries, heads)
    assert problems == [] and chains[3] == entries[2]["chain"]


def test_changed_old_entry_is_found():
    entries = make_log(VECTOR_ENTRIES + ['{"v":1,"type":"reading","fp":"cc"}'])
    heads = [{"day": "2026-11-01", "seq": 2, "chain": entries[1]["chain"]}]
    # The registry changes entry 1 and calculates all hashes again. The old head does not match.
    forged = make_log(['{"v":1,"type":"reading","fp":"zz"}'] + VECTOR_ENTRIES[1:] + ['{"v":1,"type":"reading","fp":"cc"}'])
    problems, _ = translog.verify(forged, heads)
    assert any("head 2026-11-01" in p for p in problems)
    # The registry changes the text but not the hashes.
    bad = [dict(e) for e in entries]
    bad[0]["entry"] = '{"v":1,"type":"reading","fp":"zz"}'
    assert any("entry 1" in p for p in translog.verify(bad, heads)[0])


def test_removed_entry_is_found():
    entries = make_log(VECTOR_ENTRIES + ['{"v":1,"type":"reading","fp":"cc"}'])
    problems, _ = translog.verify([entries[0], entries[2]], [])
    assert problems and "missing" in problems[0]


def test_witness_keeps_the_first_value(tmp_path):
    heads = [{"day": "2026-11-01", "chain": "a" * 64}]
    translog.save_witness(tmp_path, {}, heads)
    saved = translog.load_witness(tmp_path)
    assert translog.compare_witness(saved, heads) == []
    rewritten = [{"day": "2026-11-01", "chain": "b" * 64}]
    assert translog.compare_witness(saved, rewritten) == ["2026-11-01"]
    assert translog.compare_witness(saved, []) == ["2026-11-01"]  # A removed head is also a change.
    translog.save_witness(tmp_path, saved, rewritten)
    assert translog.load_witness(tmp_path)["2026-11-01"] == "a" * 64  # The evidence stays.


def test_check_reading():
    card = "ab" * 32
    reading = {"date": "2026-11-01", "verdict": "KEEP", "perf": {"bf16_tflops": 232.2, "fraction": 1}}
    canonical = json.dumps(reading, sort_keys=True, separators=(",", ":"))
    fp = translog.sha256_hex(f"dud-log-v1:reading:{card}:{canonical}")
    shown = dict(reading, trust="low", yours=False, log={"seq": 1, "fp": fp, "canonical": canonical})
    assert translog.check_reading(card, shown) is None
    assert "different" in translog.check_reading(card, dict(shown, verdict="KILL"))
    assert "fingerprint" in translog.check_reading("cd" * 32, shown)


def test_receipts(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "registry_response.json").write_text(json.dumps({"status": "accepted", "receipts": [{"gpu_index": 0, "fp": "f1"}]}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "registry_response.json").write_text(json.dumps({"status": "rejected", "receipts": []}))
    assert translog.receipts(tmp_path) == ["f1"]
