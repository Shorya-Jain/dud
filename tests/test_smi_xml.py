import pytest

from dud import ids
from dud.collect import smi_xml
from conftest import FIXTURES


def parse(name):
    return smi_xml.parse((FIXTURES / name / "nvidia-smi-q-x.xml").read_text())


def val(field):
    assert field["status"] == "ok", field
    return field["value"]


def test_healthy_h100_identity():
    p = parse("h100_sxm_healthy")
    assert val(p["top"]["driver_version"]) == "550.90.07"
    assert val(p["top"]["attached_gpus"]) == 8
    assert len(p["gpus"]) == 8
    g = p["gpus"][0]
    assert g["bus_id"] == "00000000:18:00.0"
    i = g["identity"]
    assert val(i["name"]) == "NVIDIA H100 80GB HBM3"
    assert val(i["memory_total_mib"]) == 81559
    assert val(i["power_limit_default_w"]) == 700.0
    assert val(i["power_limit_current_w"]) == 700.0
    assert val(i["pcie"]["gen_max"]) == 5
    assert val(i["pcie"]["width_current"]) == 16
    assert val(i["max_clocks"]["sm_mhz"]) == 1980
    assert val(i["fabric_state"]) == "Completed"
    assert val(g["snapshot"]["throttle_reasons_active"]) == ["gpu_idle"]


def test_healthy_h100_history():
    p = parse("h100_sxm_healthy")
    h = p["gpus"][3]["history"]
    assert val(h["ecc_mode"]) is True
    assert val(h["ecc"]["aggregate"]["correctable"]) == 12
    assert val(h["ecc"]["aggregate"]["uncorrectable"]) == 0
    assert val(h["ecc"]["volatile"]["uncorrectable"]) == 0
    assert val(h["ecc"]["aggregate"]["detail"])["sram_threshold_exceeded"] is False
    assert val(h["row_remap"]["pending"]) is False
    assert val(h["row_remap"]["bank_availability"]["max"]) == 2560
    # H100 does not use retired pages: nvidia-smi shows N/A.
    assert h["retired_pages"]["correctable"]["reason"] == "smi_na"


def test_pending_remap_values():
    h = parse("h100_sxm_pending_remap")["gpus"][0]["history"]
    assert val(h["ecc"]["volatile"]["uncorrectable"]) == 2
    assert val(h["ecc"]["aggregate"]["correctable"]) == 41
    assert val(h["row_remap"]["uncorrectable"]) == 1
    assert val(h["row_remap"]["pending"]) is True
    assert val(h["row_remap"]["bank_availability"]["high"]) == 4


def test_old_driver_format_a100():
    g = parse("a100_80gb_pcie")["gpus"][0]
    i, h = g["identity"], g["history"]
    assert val(i["power_limit_current_w"]) == 300.0  # From <enforced_power_limit>.
    assert val(i["pcie"]["gen_current"]) == 1
    assert val(h["ecc"]["aggregate"]["correctable"]) == 3
    assert "sram_uncorrectable" in val(h["ecc"]["aggregate"]["detail"])
    assert h["row_remap"]["bank_availability"]["max"]["reason"] == "not_in_output"
    assert val(g["snapshot"]["throttle_reasons_active"]) == ["gpu_idle"]


def test_whole_section_na_is_smi_na():
    h = parse("container_ecc_hidden")["gpus"][0]["history"]
    for f in (h["ecc"]["volatile"]["uncorrectable"], h["row_remap"]["pending"],
              h["row_remap"]["bank_availability"]["low"], h["ecc_mode"]):
        assert f["status"] == "not_supported"
        assert f["reason"] == "smi_na"
        assert f["value"] is None


def test_legacy_single_double_bit_format():
    xml = """<nvidia_smi_log><gpu id="0000:01:00.0"><ecc_errors>
      <volatile>
        <single_bit><device_memory>1</device_memory><total>4</total></single_bit>
        <double_bit><device_memory>0</device_memory><total>2</total></double_bit>
      </volatile>
    </ecc_errors></gpu></nvidia_smi_log>"""
    h = smi_xml.parse(xml)["gpus"][0]["history"]
    assert val(h["ecc"]["volatile"]["correctable"]) == 4
    assert val(h["ecc"]["volatile"]["uncorrectable"]) == 2
    assert val(h["ecc"]["volatile"]["detail"])["single_bit.total"] == 4
    assert h["ecc"]["aggregate"]["correctable"]["reason"] == "not_in_output"


@pytest.mark.parametrize("raw,expected", [
    (None, ("not_supported", "not_in_output")),
    ("N/A", ("not_supported", "smi_na")),
    ("[N/A]", ("not_supported", "smi_na")),
    ("[Insufficient Permissions]", ("blocked", "smi_insufficient_permissions")),
    ("[Not Supported]", ("not_supported", "smi_not_supported")),
    ("[Unknown Error]", ("error", "smi_error")),
    ("[GPU requires reset]", ("error", "smi_error")),
    ("81559 MiB", None),
])
def test_classify(raw, expected):
    assert smi_xml.classify(raw) == expected


def test_unit_mismatch_is_parse_error():
    import xml.etree.ElementTree as ET
    el = ET.fromstring("<g><total>80 GiB</total></g>")
    f = smi_xml.f_num(el, "total", "MiB")
    assert (f["status"], f["reason"], f["detail"]) == ("error", "parse_failed", "80 GiB")


def test_redacted_xml_gives_same_card_ids(fixture_name):
    raw = (FIXTURES / fixture_name / "nvidia-smi-q-x.xml").read_text()
    redacted, _ = ids.redact_smi_xml(raw)
    a, b = smi_xml.parse(raw), smi_xml.parse(redacted)
    for ga, gb in zip(a["gpus"], b["gpus"]):
        assert ga["card"] == gb["card"]
        assert ga["card"]["uuid_sha256"]["status"] == "ok"
        assert ga["history"] == gb["history"]


def test_bad_xml_raises():
    with pytest.raises(smi_xml.SmiParseError):
        smi_xml.parse("<nvidia_smi_log><gpu>")
    with pytest.raises(smi_xml.SmiParseError):
        smi_xml.parse("<html></html>")
