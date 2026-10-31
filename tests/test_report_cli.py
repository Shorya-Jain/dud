import json

import pytest

from dud import cli, report
from dud import text as T
from conftest import FIXTURES, raw_ids, run


def test_report_renders(fixture_name):
    doc = run(fixture_name)
    md = report.render(doc)
    assert md.startswith("# dud report")
    assert T.MOCK_BANNER in md
    for g in doc["gpus"]:
        assert f"## GPU {g['index']}:" in md
    for secret in raw_ids(fixture_name):
        assert secret not in md


def test_report_content_pending_remap():
    md = report.render(run("h100_sxm_pending_remap"))
    assert "| Pending row remap | Yes | Available |" in md
    assert "| 94 |" in md and "| 63 |" in md
    assert "pid=" not in md


def test_report_groups_blocked_values():
    md = report.render(run("container_ecc_hidden"))
    line = next(l for l in md.splitlines() if T.REASONS["hidden_on_supported_model"] in l)
    assert line.startswith("- **Blocked**: ECC mode, ")
    assert "Bank availability: none" in line


def test_report_marks_nvml_values():
    md = report.render(run("a100_80gb_pcie"))
    assert f"| Bank availability: maximum | 640 | {T.STATUS_FROM_NVML} |" in md


def test_terminal_summary():
    s = report.terminal_summary(run("container_ecc_hidden"))
    assert s.splitlines()[1].split()[-1] == "19"
    assert "Blocked" in s


@pytest.fixture
def mock_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DUD_MOCK", "1")
    monkeypatch.setenv("DUD_FIXTURES_DIR", str(FIXTURES))
    monkeypatch.setenv("DUD_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DUD_TOKEN", raising=False)
    monkeypatch.delenv("DUD_API_URL", raising=False)
    out = tmp_path / "out"
    out.mkdir()
    return out


def test_cli_quick_and_report(mock_env, capsys, monkeypatch):
    monkeypatch.setenv("DUD_FIXTURE", "h100_sxm_pending_remap")
    assert cli.main(["quick", "--provider", "vast.ai", "--out-dir", str(mock_env)]) == 0
    out = capsys.readouterr().out
    assert T.MOCK_BANNER in out
    (folder,) = list(mock_env.iterdir())
    result = folder / "result.json"
    assert json.loads(result.read_text())["run"]["provider"]["reported"] == "vast.ai"
    assert (folder / "report.md").is_file()
    assert sorted(p.name for p in (folder / "raw").iterdir()) == [
        "kernel_log.txt", "nvml_snapshot.txt", "smi_q_x.txt", "smi_topo_m.txt"]
    assert cli.main(["report", str(result)]) == 0
    assert capsys.readouterr().out.strip() == (folder / "report.md").read_text().strip()


def test_cli_errors(mock_env, capsys, monkeypatch):
    monkeypatch.setenv("DUD_FIXTURE", "h100_sxm_healthy")
    assert cli.main(["quick", "--gpus", "0,x", "--out-dir", str(mock_env)]) == 1
    assert T.BAD_GPUS_FLAG in capsys.readouterr().err
    assert cli.main(["quick", "--gpus", "9", "--out-dir", str(mock_env)]) == 1
    assert "GPU 9 is not on this node" in capsys.readouterr().err
    monkeypatch.setenv("DUD_FIXTURE", "no_such_fixture")
    assert cli.main(["quick", "--out-dir", str(mock_env)]) == 1
    assert "no_such_fixture" in capsys.readouterr().err
    monkeypatch.setenv("DUD_FIXTURE", "h100_sxm_healthy")
    assert cli.main(["full", "--out-dir", str(mock_env)]) == 1  # Not signed in.
    assert T.NOT_LOGGED_IN in capsys.readouterr().err
    assert cli.main(["status"]) == 1
    bad = mock_env / "bad.json"
    bad.write_text('{"kind": "other"}')
    assert cli.main(["report", str(bad)]) == 1
    assert "not a dud result file" in capsys.readouterr().err
