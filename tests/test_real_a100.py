"""The fixture from a real A100 SXM4 40GB (Vast.ai, driver 615). See fixtures/README.md."""
import json

from conftest import FIXTURES, probe, run
from dud import grade
from dud.collect import dcgm, smi_xml

NAME = "a100_sxm4_40gb_real"


def test_identity_and_driver_615_names():
    doc = run(NAME)
    g = doc["gpus"][0]
    assert g["identity"]["model_key"]["value"] == "A100-SXM4-40GB"
    assert g["identity"]["memory_total_mib"]["value"] == 39936
    assert doc["host"]["driver_version"]["value"] == "615.71.09"
    # Driver 615: average_power_draw is N/A, instant_power_draw has the value.
    assert g["snapshot"]["power_draw_w"]["value"] == 52.13
    # Driver 615: gpu_recovery_action in place of gpu_reset_status.
    assert g["snapshot"]["reset_required"]["value"] is False


def test_memory_is_inside_the_datasheet_range():
    spec = grade.specs()["models"]["A100-SXM4-40GB"]["memory_mib"]
    assert spec["min"] <= 39936 <= spec["max"]


def test_lowered_power_limit_is_a_finding():
    g = run(NAME)["gpus"][0]
    codes = {f["code"]: f for f in g["findings"]}
    assert codes["power_limit_below_default"]["detail"] == "300 W of 400 W"


def test_dcgm_4_7_output():
    parsed = dcgm.parse((FIXTURES / NAME / "dcgm-diag.json").read_text())
    g = dcgm.per_gpu(parsed, 0)
    assert g["result"] == "pass"
    names = {t["name"]: t["result"] for t in g["tests"]}
    assert names["memory"] == "pass" and names["targeted_power"] == "pass" and names["nvbandwidth"] == "skip"


def _xml(body: str) -> str:
    return f"<nvidia_smi_log><timestamp>x</timestamp>{body}<attached_gpus>0</attached_gpus></nvidia_smi_log>"


def test_deprecated_top_level_names():
    top = smi_xml.parse(_xml("<kmd_version>700.1</kmd_version><cuda_umd_version>14.0</cuda_umd_version>"))["top"]
    assert top["driver_version"]["value"] == "700.1" and top["cuda_version"]["value"] == "14.0"
    top = smi_xml.parse(_xml("<driver_version>615.71.09</driver_version><kmd_version>615.71.09</kmd_version>"))["top"]
    assert top["driver_version"]["value"] == "615.71.09"


def test_recovery_action_values():
    import xml.etree.ElementTree as ET

    for action, expect in (("None", False), ("GPU Reset", True), ("Node Reboot", True), ("Drain P2P", False),
                           ("Drain and Reset", True)):
        g = ET.fromstring(f"<gpu><gpu_recovery_action>{action}</gpu_recovery_action></gpu>")
        assert smi_xml._reset_required(g)["value"] is expect, action
    g = ET.fromstring("<gpu><gpu_reset_status><reset_required>Yes</reset_required></gpu_reset_status></gpu>")
    assert smi_xml._reset_required(g)["value"] is True


def test_fixture_has_no_raw_identifiers():
    spec = json.loads((FIXTURES / NAME / "fixture.json").read_text())
    assert spec["synthetic"] is False
    text = "".join(p.read_text() for p in (FIXTURES / NAME).iterdir())
    import re

    assert not re.search(r"GPU-[0-9a-f]{8}-", text)
