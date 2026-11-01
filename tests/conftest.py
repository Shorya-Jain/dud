import json
from pathlib import Path

import pytest

from dud.collect import collect
from dud.probe import MockProbe

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
FIXTURE_NAMES = ["h100_sxm_healthy", "h100_sxm_pending_remap", "a100_80gb_pcie", "container_ecc_hidden", "a100_sxm4_40gb_real"]
SCHEMA = json.loads((ROOT / "src" / "dud" / "schema" / "result.v1.json").read_text())


def probe(name: str) -> MockProbe:
    return MockProbe(FIXTURES / name)


def run(name: str, **kw) -> dict:
    return collect(probe(name), mode="quick", **kw)


def raw_ids(name: str) -> list:
    """Every raw UUID, serial number and process name in a fixture. None may appear in output."""
    import re

    xml = (FIXTURES / name / "nvidia-smi-q-x.xml").read_text()
    found = re.findall(r"<(?:uuid|serial)>([^<]+)</", xml)
    found += re.findall(r"<process_name>([^<]+)</", xml)
    # A fixture from a real node has redaction markers in place of the raw values.
    return [f for f in found if f != "N/A" and not f.startswith("dud-redacted:")]


@pytest.fixture(params=FIXTURE_NAMES)
def fixture_name(request):
    return request.param
