import json
import os
import re
import shutil
import socket
import stat
import subprocess
import time

import pytest

from dud import challenge as ch
from dud import cli, history, registry
from dud import text as T
from conftest import FIXTURES, ROOT, run


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("DUD_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DUD_TOKEN", raising=False)
    monkeypatch.delenv("DUD_API_URL", raising=False)
    return tmp_path / "home"


def test_credentials_are_private(home):
    assert registry.load_credentials() is None
    path = registry.save_credentials("https://r.example", "dud_secret", "alice")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert registry.load_credentials()["token"] == "dud_secret"
    assert registry.api_url() == "https://r.example"
    assert registry.delete_credentials() is True
    assert registry.delete_credentials() is False


def test_env_overrides(home, monkeypatch):
    monkeypatch.setenv("DUD_TOKEN", "dud_from_env")
    monkeypatch.setenv("DUD_API_URL", "http://localhost:1/")
    assert registry.load_credentials()["token"] == "dud_from_env"
    assert registry.api_url() == "http://localhost:1"


def fake_github(replies):
    calls = []

    def post(url, body):
        calls.append((url, body))
        if url == registry.GITHUB_DEVICE_URL:
            return 200, {"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device",
                         "interval": 5, "expires_in": 900}
        return 200, replies.pop(0)
    return post, calls


def test_device_flow():
    post, calls = fake_github([{"error": "authorization_pending"}, {"error": "slow_down", "interval": 10},
                               {"access_token": "gho_x"}])
    shown, sleeps = [], []
    token = registry.github_device_flow("Iv1.abc", lambda c, u: shown.append((c, u)), post=post, sleep=sleeps.append)
    assert token == "gho_x"
    assert shown == [("ABCD-1234", "https://github.com/login/device")]
    assert sleeps == [5, 5, 10]
    assert calls[1][1]["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"


def test_device_flow_denied_and_expired():
    post, _ = fake_github([{"error": "access_denied"}])
    with pytest.raises(registry.RegistryError, match="did not approve"):
        registry.github_device_flow("id", lambda c, u: None, post=post, sleep=lambda s: None)
    post, _ = fake_github([{"error": "expired_token"}])
    with pytest.raises(registry.RegistryError, match="did not start"):
        registry.github_device_flow("id", lambda c, u: None, post=post, sleep=lambda s: None)


def test_unreachable_registry(home, monkeypatch):
    monkeypatch.setenv("DUD_API_URL", "http://127.0.0.1:9")
    with pytest.raises(registry.RegistryError, match="cannot connect"):
        registry.Client(token="dud_x").me()


def test_challenge_python_side_matches_vectors():
    v = json.loads((FIXTURES / "challenge_vectors.json").read_text())
    p = v["params"]
    assert ch.seed_for(v["nonce"], v["card_id"]) == v["seed"]
    assert ch.digests_ref(v["seed"], p, 5) == v["digests"]
    levels = ch.merkle_levels(v["digests"])
    assert levels[-1][0].hex() == v["merkle_root"]
    assert ch.merkle_proof(levels, 3) == v["proof_j3"]


def test_run_rounds_and_reveal():
    p = {"m": 4, "n": 3, "k": 8, "pool": 2, "batch": 2}
    rounds = [{"gpu_index": 0, "seed": 11, "params": p, "count": 5}, {"gpu_index": 1, "seed": 22, "params": p, "count": 3}]
    runners = {0: ch.ReferenceRunner(), 1: ch.ReferenceRunner()}
    commits, state = ch.run_rounds(rounds, runners)
    assert [c["gpu_index"] for c in commits] == [0, 1]
    r = ch.reveal({"gpu_index": 1, "j": 2}, {x["gpu_index"]: x for x in rounds}, state, runners)
    assert r["digest"] == ch.digests_ref(22, p, 3)[2]
    assert len(r["proof"]) == 2
    assert ch.self_test(ch.ReferenceRunner())


def test_history_finding_when_counter_is_lower():
    doc = run("h100_sxm_pending_remap")
    card = doc["gpus"][0]["card"]["uuid_sha256"]["value"]
    reading = {"date": "2026-09-01", "provider": "x", "trust": "normal",
               "ecc": {"aggregate_correctable": 50, "aggregate_uncorrectable": 2},
               "row_remap": {"correctable": 3, "uncorrectable": 1, "pending": False}}
    doc["registry"] = {"status": "ok", "message": None, "cards": {card: {"readings": [reading], "contributors": 1}}}
    history.compare(doc)
    f = doc["gpus"][0]["findings"]
    assert [x["code"] for x in f] == ["counter_lower_than_registry"]
    assert f[0]["path"] == "history.ecc.aggregate.correctable"


# --- End to end against the local dev registry (needs Node 22.18 or later) ------------------

def _node_ok() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    return tuple(int(x) for x in out.split(".")[:2]) >= (22, 18)


@pytest.fixture
def dev_registry(home, monkeypatch, tmp_path):
    if not _node_ok():
        pytest.skip("Node 22.18 or later is not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(["node", str(ROOT / "server" / "dev.ts"), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines, token = [], None
    deadline = time.time() + 20
    while time.time() < deadline and token is None:
        line = proc.stdout.readline()
        lines.append(line)
        m = re.search(r"Token for the account \"dev\": (dud_\S+)", line)
        token = m.group(1) if m else None
    if token is None:
        proc.kill()
        pytest.fail("dev server did not start: " + "".join(lines))
    monkeypatch.setenv("DUD_API_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("DUD_TOKEN", token)
    monkeypatch.setenv("DUD_MOCK", "1")
    monkeypatch.setenv("DUD_FIXTURES_DIR", str(FIXTURES))
    yield port
    proc.kill()
    proc.wait()


def test_end_to_end_full_then_quick(dev_registry, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DUD_FIXTURE", "h100_sxm_pending_remap")
    out = tmp_path / "out"
    # Before a full test: no access.
    assert cli.main(["quick", "--out-dir", str(out / "q1")]) == 0
    assert "You do not have registry access" in capsys.readouterr().out

    assert cli.main(["full", "--provider", "testcloud", "--out-dir", str(out / "full")]) == 0, capsys.readouterr()
    text = capsys.readouterr().out
    assert "Challenge: the registry accepted the work" in text
    assert "You have registry access until" in text, text
    (folder,) = list((out / "full").iterdir())
    resp = json.loads((folder / "registry_response.json").read_text())
    assert resp["status"] == "accepted" and resp["grants_access"] is True
    result = json.loads((folder / "result.json").read_text())
    assert result["challenge"]["challenge_id"].startswith("chl_")

    assert cli.main(["status"]) == 0
    assert "You have registry access until" in capsys.readouterr().out

    # After a full test: the quick test shows the earlier reading.
    assert cli.main(["quick", "--out-dir", str(out / "q2")]) == 0
    text = capsys.readouterr().out
    assert "the registry has 1 earlier readings from 1 accounts" in text, text
    (q2,) = list((out / "q2").iterdir())
    assert "## Registry history" in (q2 / "report.md").read_text()

    # The same node again: the challenge is new, the XML time is new, so it is accepted again.
    time.sleep(1.1)
    assert cli.main(["full", "--out-dir", str(out / "full2")]) == 0
    assert "You have registry access until" in capsys.readouterr().out


def test_end_to_end_no_submit(dev_registry, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DUD_FIXTURE", "a100_80gb_pcie")
    assert cli.main(["full", "--no-submit", "--out-dir", str(tmp_path / "o")]) == 0
    assert T.SUBMIT_SKIPPED in capsys.readouterr().out
