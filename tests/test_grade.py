import json
from datetime import datetime, timedelta, timezone

import jsonschema
import pytest

from dud import bench, grade, model
from dud import text as T
from dud.collect import collect, dcgm
from dud.fulltest import run_tests
from conftest import FIXTURES, ROOT, SCHEMA, probe, raw_ids, run

EXPECTED = {
    "h100_sxm_healthy": ("KEEP", []),
    "h100_sxm_pending_remap": ("KILL", ["uncorrectable_ecc_since_reset", "pending_row_remap", "dcgm_diagnostic"]),
    "a100_80gb_pcie": ("KILL", ["sustained_performance", "persistent_throttling"]),
    "container_ecc_hidden": ("UNKNOWN", []),
}


def full(name: str, minutes: int = 15, skip_dcgm: bool = False) -> dict:
    p = probe(name)
    doc = collect(p, mode="full", options={"gpus": None, "load_minutes": minutes, "skip_dcgm": skip_dcgm, "submit": False})
    run_tests(p, doc, load_minutes=minutes, skip_dcgm=skip_dcgm, gpus=None, say=lambda *a: None)
    return doc


@pytest.mark.parametrize("name", list(EXPECTED))
def test_full_verdicts(name):
    doc = full(name)
    jsonschema.validate(doc, SCHEMA)
    verdict, failing = EXPECTED[name]
    assert doc["node"]["verdict"]["verdict"] == verdict
    g = doc["gpus"][0]
    assert sorted(r["rule"] for r in g["verdict"]["results"] if r["result"] == "fail") == sorted(failing)
    assert g["verdict"]["summary"]


def test_full_doc_has_no_raw_identifiers():
    doc = full("h100_sxm_healthy")
    text = json.dumps(doc) + "".join(model.raw_text(e) for e in doc["raw"])
    for secret in raw_ids("h100_sxm_healthy"):
        assert secret not in text
    assert {e["id"] for e in doc["raw"]} >= {"smi_q_x_after", "dcgm_diag", "perf_log"}


def test_unknown_explains_hidden_values():
    g = full("container_ecc_hidden")["gpus"][0]
    missing = [r["rule"] for r in g["verdict"]["results"] if r["result"] == "missing"]
    assert "uncorrectable_ecc_since_reset" in missing and "pending_row_remap" in missing
    assert "dcgm_diagnostic" not in missing  # DCGM missing is skipped, not unknown.
    assert T.REASONS["dcgm_not_installed"] and g["diag"]["dcgm_result"]["reason"] == "dcgm_not_installed"


def test_perf_values_and_p2p():
    doc = full("h100_sxm_healthy", minutes=2)
    g = doc["gpus"][3]
    assert g["perf"]["bf16_tflops"]["value"] == pytest.approx(751.3)
    assert g["perf"]["sustained_bf16_tflops"]["status"] == "ok"
    # Power cap from 60 s, in 55 % of samples: about 27 % of a 2-minute run.
    assert 0.15 < g["perf"]["power_capped_fraction"]["value"] < 0.4
    assert g["perf"]["throttle_hw_fraction"]["value"] == 0
    assert len(g["load"]["series"]["t_s"]) == 120
    pairs = doc["node"]["p2p_bandwidth"]["value"]["pairs"]
    assert len(pairs) == 56 and all(p["peer_access"] for p in pairs)
    one = full("a100_80gb_pcie", minutes=1)
    assert one["node"]["p2p_bandwidth"]["reason"] == "single_gpu"
    assert one["gpus"][0]["perf"]["fp8_tflops"]["status"] == "not_supported"


def test_skip_dcgm_and_no_torch():
    doc = full("h100_sxm_healthy", minutes=1, skip_dcgm=True)
    assert doc["gpus"][0]["diag"]["dcgm_result"]["reason"] == "dcgm_skipped_by_user"
    doc = run("h100_sxm_healthy")
    bench.skip_all(doc, "torch_missing")
    doc["run"]["mode"] = "full"
    for g in doc["gpus"]:
        g["diag"] = {**dcgm.skipped("dcgm_skipped_by_user"), "ecc_uncorrectable_delta": model.ok(0, "derived"),
                     "ecc_correctable_delta": model.ok(0, "derived"), "row_remap_pending_after": model.ok(False, "derived")}
    grade.grade_doc(doc)
    assert doc["node"]["verdict"]["verdict"] == "UNKNOWN"


@pytest.mark.parametrize("name,expected", [
    ("h100_sxm_healthy", "KEEP"), ("h100_sxm_pending_remap", "KILL"),
    ("a100_80gb_pcie", "KEEP"), ("container_ecc_hidden", "UNKNOWN"),
])
def test_quick_verdicts_use_history_only(name, expected):
    doc = run(name)
    grade.grade_doc(doc)
    assert doc["node"]["verdict"]["verdict"] == expected
    assert all(r["rule"] not in ("sustained_performance", "dcgm_diagnostic") for r in doc["gpus"][0]["verdict"]["results"])


def _with_registry(name: str, readings: list) -> dict:
    doc = run(name)
    card = doc["gpus"][0]["card"]["uuid_sha256"]["value"]
    doc["registry"] = {"status": "ok", "message": None, "cards": {card: {"readings": readings, "contributors": 2}}}
    grade.grade_doc(doc)
    return doc["gpus"][0]["verdict"]


def _day(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def test_quick_recent_keep_means_start_work():
    v = _with_registry("a100_80gb_pcie", [{"date": _day(6), "verdict": "KEEP"}])
    assert v["verdict"] == "KEEP"
    assert v["summary"] == T.REGISTRY_RECENT_KEEP.format(when=T.WHEN_DAYS.format(days=6))
    assert v["registry"]["days_ago"] == 6
    today = _with_registry("a100_80gb_pcie", [{"date": _day(0), "verdict": "KEEP"}])
    assert today["summary"] == T.REGISTRY_RECENT_KEEP.format(when=T.WHEN_TODAY)


def test_quick_recent_keep_but_counts_went_up():
    # The A100 fixture has 3 aggregate correctable ECC errors now. The registry reading had 1.
    reading = {"date": _day(1), "verdict": "KEEP", "ecc": {"aggregate_correctable": 1, "aggregate_uncorrectable": 0},
               "row_remap": {"correctable": 0, "uncorrectable": 0}}
    v = _with_registry("a100_80gb_pcie", [reading])
    assert v["verdict"] == "KEEP"
    assert v["summary"] == T.REGISTRY_KEEP_COUNTS_UP.format(when=T.WHEN_ONE_DAY)


def test_quick_kill_on_record_wins():
    v = _with_registry("a100_80gb_pcie", [{"date": "2026-09-02", "verdict": "KILL"}, {"date": _day(3), "verdict": "KEEP"}])
    assert v["verdict"] == "KILL"
    assert v["local_verdict"] == "KEEP"
    assert v["summary"].startswith(T.REGISTRY_KILL.format(date="2026-09-02"))


def test_quick_old_keep_is_not_recent():
    v = _with_registry("a100_80gb_pcie", [{"date": _day(90), "verdict": "KEEP"}])
    assert v["verdict"] == "KEEP"
    assert v["summary"] == T.VERDICT_ALL_PASSED


def test_quick_unknown_now_but_recent_keep():
    v = _with_registry("container_ecc_hidden", [{"date": _day(2), "verdict": "KEEP"}])
    assert v["verdict"] == "UNKNOWN"
    assert v["summary"].endswith(T.REGISTRY_KEEP_BUT_UNKNOWN.format(when=T.WHEN_DAYS.format(days=2)))


def test_dcgm_parser():
    text = (FIXTURES / "h100_sxm_pending_remap" / "dcgm-diag.json").read_text()
    parsed = dcgm.parse("some banner line\n" + text)
    assert parsed["version"] == "3.3.7"
    g = dcgm.per_gpu(parsed, 0)
    assert g["result"] == "fail"
    failed = [t for t in g["tests"] if t["result"] == "fail"]
    assert failed[0]["name"] == "Page Retirement/Row Remap" and "pending" in failed[0]["info"]
    other = dcgm.parse(json.dumps({"tests": [{"name": "X", "results": [{"entity_id": 1, "status": "Warn"}]}]}))
    assert dcgm.per_gpu(other, 1)["result"] == "warn"
    assert dcgm.per_gpu(other, 0)["tests"] == []
    with pytest.raises(dcgm.DcgmParseError):
        dcgm.parse("Error: unable to connect to host engine")
    assert dcgm.argv([0, 2]) == ["dcgmi", "diag", "-r", "3", "-j", "-i", "0,2"]


def test_summarize_load_ignores_warmup():
    s = {"t_s": [1.0, 2.0, 40.0, 41.0], "tflops": [10, 10, 700, 702], "throttle_mask": [0, 0x40, 4, 0], "temp_c": [30, 31, 60, 61]}
    out = bench.summarize_load({"interval_s": 1, "minutes": 1, "series": s}, None)
    assert out["sustained_bf16_tflops"]["value"] == 701
    assert out["throttle_hw_fraction"]["value"] == 0.25
    assert out["power_capped_fraction"]["value"] == 0.25
    assert out["max_temp_c"]["value"] == 61


def test_packaged_rules_match_yaml():
    import yaml

    for name in ("grading", "specs"):
        packaged = json.loads((ROOT / "src" / "dud" / "rules" / f"{name}.json").read_text())
        source = yaml.safe_load((ROOT / f"{name}.yaml").read_text())
        if name == "specs":
            source = {"challenge": source["challenge"], "models": source["models"]}
        assert packaged == source, f"run scripts/build_specs.py ({name})"
        assert json.loads((ROOT / "server" / "src" / f"{name}.json").read_text()) == source
