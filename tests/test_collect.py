import copy
import json

import jsonschema
import pytest

from dud import ids, model
from dud.collect import UnknownGpu, collect
from conftest import SCHEMA, probe, raw_ids, run


def all_text(doc: dict) -> str:
    """The result file as text, with every raw output decoded."""
    return json.dumps(doc) + "".join(model.raw_text(e) for e in doc["raw"])


def test_every_fixture_matches_schema(fixture_name):
    jsonschema.validate(run(fixture_name), SCHEMA)


def test_no_raw_identifier_leaves_the_node(fixture_name):
    text = all_text(run(fixture_name))
    for secret in raw_ids(fixture_name) + ["secret-host-01", "other_tenant_job", "pid=51234"]:
        assert secret not in text, secret


def test_raw_hashes_match_content(fixture_name):
    for entry in run(fixture_name)["raw"]:
        assert model.sha256_text(model.raw_text(entry)) == entry["sha256"]
        assert entry["bytes"] == len(model.raw_text(entry).encode())


def test_same_output_gives_same_raw_hash():
    # The registry finds replayed submissions by this hash (milestone 3).
    a, b = run("h100_sxm_healthy"), run("h100_sxm_healthy")
    assert a["raw"][0]["sha256"] == b["raw"][0]["sha256"]
    assert a["raw"][0]["content"] == b["raw"][0]["content"]
    assert a["run"]["run_id"] != b["run"]["run_id"]


def test_healthy_node():
    doc = run("h100_sxm_healthy", provider="lambda")
    assert doc["run"]["mock"] is True and doc["run"]["fixture"] == "h100_sxm_healthy"
    assert doc["run"]["provider"]["reported"] == "lambda"
    assert doc["node"]["gpu_count"] == 8 and len(doc["gpus"]) == 8
    assert len({g["card"]["uuid_sha256"]["value"] for g in doc["gpus"]}) == 8
    g = doc["gpus"][0]
    assert g["card"]["uuid_sha256"]["value"] == ids.uuid_hash("GPU-5e1a7c3d-90b2-4f61-8c3e-a1b2c3d4e500")
    assert g["identity"]["model_key"]["value"] == "H100-SXM5-80GB"
    assert g["identity"]["form_factor"]["value"] == "SXM"
    assert g["identity"]["nvlink"]["value"]["links_active"] == 18
    assert g["history"]["xid_events"]["value"] == []
    assert g["findings"] == [] and doc["findings"] == []
    assert model.visibility_counts(g)["blocked"] == 0
    h = doc["host"]
    assert h["topology"]["value"]["rows"]["GPU0"]["GPU7"] == "NV18"
    assert h["environment"]["virtualization"]["value"] == "kvm"
    assert h["environment"]["container"]["value"] == "none"
    assert h["environment"]["is_root"]["value"] is True
    raw = {e["id"]: e for e in doc["raw"]}
    assert set(raw) == {"smi_q_x", "smi_topo_m", "kernel_log", "nvml_snapshot"}
    assert raw["smi_q_x"]["redactions"] == ["processes", "serial", "uuid"]


def test_pending_remap_node():
    doc = run("h100_sxm_pending_remap")
    g = doc["gpus"][0]
    assert g["history"]["row_remap"]["pending"]["value"] is True
    assert g["snapshot"]["reset_required"]["value"] is True
    xids = g["history"]["xid_events"]["value"]
    assert [e["xid"] for e in xids] == [94, 63]  # XID 79 is for a GPU on another bus.
    assert doc["host"]["environment"]["container"]["value"] == "docker"


def test_a100_uses_nvml_for_bank_availability():
    g = run("a100_80gb_pcie")["gpus"][0]
    assert g["identity"]["model_key"]["value"] == "A100-PCIE-80GB"
    f = g["history"]["row_remap"]["bank_availability"]["max"]
    assert (f["status"], f["value"], f["source"], f["reason"]) == ("ok", 640, "nvml", "from_nvml")
    assert g["history"]["retired_pages"]["correctable"]["reason"] == "replaced_by_row_remap"
    assert g["identity"]["nvlink"]["status"] == "not_supported"
    assert g["history"]["xid_events"]["status"] == "blocked"


def test_hidden_ecc_is_blocked_not_unsupported():
    doc = run("container_ecc_hidden")
    for g in doc["gpus"]:
        h = g["history"]
        for f in (h["ecc_mode"], h["ecc"]["volatile"]["uncorrectable"], h["ecc"]["aggregate"]["correctable"],
                  h["row_remap"]["pending"], h["row_remap"]["bank_availability"]["max"]):
            assert (f["status"], f["reason"]) == ("blocked", "hidden_on_supported_model")
        assert h["retired_pages"]["pending"]["status"] == "not_supported"
    env = doc["host"]["environment"]
    assert env["container"]["value"] == "kubernetes"
    assert env["is_root"]["value"] is False
    assert env["dmi_vendor"]["status"] == "blocked"
    assert doc["host"]["kernel_log"]["status"] == "blocked"
    assert doc["run"]["utc_offset_s"] == -25200


def test_unknown_model_keeps_na_as_not_supported():
    p = probe("container_ecc_hidden")
    xml_file = p.folder / "nvidia-smi-q-x.xml"
    p.spec = copy.deepcopy(p.spec)
    p.spec["commands"]["nvidia-smi -q -x"] = {
        "stdout": xml_file.read_text().replace("NVIDIA H100 PCIe", "NVIDIA RTX 9999"), "exit_code": 0}
    g = collect(p, mode="quick")["gpus"][0]
    assert g["identity"]["model_key"]["reason"] == "unknown_model"
    assert g["history"]["ecc_mode"]["status"] == "not_supported"


def test_ecc_disabled_is_not_supported():
    p = probe("h100_sxm_pending_remap")
    xml = (p.folder / "nvidia-smi-q-x.xml").read_text()
    xml = xml.replace("<current_ecc>Enabled</current_ecc>", "<current_ecc>Disabled</current_ecc>")
    xml = xml.replace("<remapped_row_unc>1</remapped_row_unc>", "<remapped_row_unc>N/A</remapped_row_unc>")
    p.spec["commands"]["nvidia-smi -q -x"] = {"stdout": xml, "exit_code": 0}
    p.nvml_data = {"init_error": "missing"}
    f = collect(p, mode="quick")["gpus"][0]["history"]["row_remap"]["uncorrectable"]
    assert (f["status"], f["reason"]) == ("not_supported", "ecc_disabled")


def test_nvml_mismatch_is_a_finding():
    p = probe("h100_sxm_healthy")
    p.nvml_data["devices"][2]["memory_total_bytes"] = 40000 * 1048576
    g = collect(p, mode="quick")["gpus"][2]
    assert g["findings"][0]["code"] == "smi_nvml_mismatch"
    assert g["findings"][0]["path"] == "identity.memory_total_mib"


def test_nvml_missing():
    p = probe("h100_sxm_healthy")
    p.nvml_data = {"init_error": "missing"}
    doc = collect(p, mode="quick")
    jsonschema.validate(doc, SCHEMA)
    assert doc["host"]["nvml_version"]["reason"] == "nvml_missing"
    assert doc["gpus"][0]["identity"]["nvlink"]["reason"] == "nvml_missing"


def test_gpu_filter():
    doc = run("h100_sxm_healthy", gpu_indices=[0, 5])
    assert [g["index"] for g in doc["gpus"]] == [0, 5]
    assert doc["node"]["gpu_count"] == 8
    with pytest.raises(UnknownGpu) as e:
        run("h100_sxm_healthy", gpu_indices=[3, 8])
    assert e.value.missing == [8]


def test_no_nvidia_smi():
    p = probe("h100_sxm_healthy")
    del p.spec["commands"]["nvidia-smi -q -x"]
    doc = collect(p, mode="quick")
    jsonschema.validate(doc, SCHEMA)
    assert doc["gpus"] == []
    assert doc["findings"][0]["code"] == "no_gpus"
    assert doc["host"]["driver_version"]["reason"] == "command_not_found"


def test_duplicate_card_id_is_a_finding():
    p = probe("container_ecc_hidden")
    xml = (p.folder / "nvidia-smi-q-x.xml").read_text().replace("GPU-c0ffee00-0001", "GPU-c0ffee00-0000")
    p.spec["commands"]["nvidia-smi -q -x"] = {"stdout": xml, "exit_code": 0}
    assert collect(p, mode="quick")["findings"][0]["code"] == "duplicate_card_id"


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema_version=2),
    lambda d: d["gpus"][0]["history"]["row_remap"]["pending"].update(status="blocked"),  # value must be null
    lambda d: d["gpus"][0]["card"]["uuid_sha256"].update(value="GPU-raw-uuid"),
    lambda d: d["gpus"][0]["history"]["ecc"]["volatile"]["uncorrectable"].update(value=-1),
    lambda d: d["gpus"][0]["identity"].update(extra=1),
])
def test_schema_rejects_bad_documents(change):
    doc = run("h100_sxm_pending_remap")
    change(doc)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)
