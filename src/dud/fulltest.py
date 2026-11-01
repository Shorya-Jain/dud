"""`dud full`: collect, DCGM, the registry challenge, performance and load tests, grade, submit.

Sequence:
1. Collect identity and history.
2. DCGM diagnostic. It runs before dud starts CUDA, because DCGM can refuse to
   test a GPU that another process uses.
3. Registry challenge (if dud sends the result).
4. Performance tests and the sustained load test.
5. Read nvidia-smi again: new errors during the test.
6. Grade, save, send.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, bench, challenge, dcgm_install, grade, ids, model, report
from . import text as T
from .collect import UnknownGpu, collect, dcgm, smi_xml
from .collect.common import cmd_failure_field
from .model import DudError, missing, ok
from .registry import Client, RegistryError, api_url, load_credentials


def _gpus_for_challenge(doc: dict) -> list:
    out = []
    for g in doc["gpus"]:
        card, key = g["card"]["uuid_sha256"], g["identity"]["model_key"]
        if card["status"] != "ok" or key["status"] != "ok":
            raise DudError(T.CARD_ID_MISSING.format(index=g["index"]))
        out.append({"gpu_index": g["index"], "card_id": card["value"], "model_key": key["value"]})
    return out


def _torch_ready(required: bool) -> bool:
    """True if PyTorch with CUDA can run. Ask before an install. Raise if `required` and not ready."""
    try:
        import torch  # noqa: F401
    except ImportError:
        command = f"{sys.executable} -m pip install torch"
        print(T.TORCH_MISSING.format(command=command))
        if sys.stdin.isatty() and input(T.TORCH_ASK).strip().lower() in ("y", "yes") and subprocess.call(command.split()) == 0:
            pass
        elif required:
            raise DudError(T.TORCH_NOT_INSTALLED)
        else:
            return False
    import torch

    if not torch.cuda.is_available():
        if required:
            raise DudError(T.TORCH_NO_CUDA)
        return False
    return True


def _runners(probe, gpu_indices: list) -> dict:
    if probe.mock:
        runners = {i: challenge.ReferenceRunner() for i in gpu_indices}
    else:
        _torch_ready(required=True)
        runners = {i: challenge.TorchRunner(i) for i in gpu_indices}
    for i, r in runners.items():
        if not challenge.self_test(r):
            raise DudError(T.SELF_TEST_FAILED.format(index=i))
    return runners


def do_challenge(client: Client, probe, doc: dict) -> dict:
    gpus = _gpus_for_challenge(doc)
    runners = _runners(probe, [g["gpu_index"] for g in gpus])
    created = client.create_challenge(gpus)
    print(T.CHALLENGE_START.format(count=len(gpus)))
    rounds = {r["gpu_index"]: r for r in created["rounds"]}
    commits, state = challenge.run_rounds(created["rounds"], runners)
    committed = client.commit(created["challenge_id"], commits)
    for sample in committed["samples"]:
        client.reveal(created["challenge_id"], challenge.reveal(sample, rounds, state, runners))
    print(T.CHALLENGE_DONE.format(seconds=round(committed["elapsed_ms"] / 1000, 1)))
    by_gpu = {c["gpu_index"]: c["merkle_root"] for c in commits}
    client_elapsed = state["elapsed_s"]
    del runners, state
    if not probe.mock:
        import torch

        torch.cuda.empty_cache()
    return {
        "challenge_id": created["challenge_id"],
        "nonce": created["nonce"],
        "issued_at": created["issued_at"],
        "rounds": [{"gpu_index": g["gpu_index"], "card_id": g["card_id"], "model_key": g["model_key"],
                    "count": rounds[g["gpu_index"]]["count"], "merkle_root": by_gpu[g["gpu_index"]]} for g in gpus],
        "client_elapsed_s": client_elapsed,
        "server_elapsed_ms": committed["elapsed_ms"],
        "samples": committed["samples"],
    }


def _after_test(probe, doc: dict, store: model.RawStore) -> dict:
    """Read nvidia-smi again. Return {card ID: parsed GPU} and store the raw output."""
    r = probe.run(["nvidia-smi", "-q", "-x"])
    parsed = {}
    if r.ok:
        try:
            for g in smi_xml.parse(r.stdout)["gpus"]:
                store.secrets.update(ids.secrets_for(g["uuid"], g["serial"]))
                if g["card"]["uuid_sha256"]["status"] == "ok":
                    parsed[g["card"]["uuid_sha256"]["value"]] = g
        except smi_xml.SmiParseError:
            pass
    text, redactions = ids.redact_smi_xml(r.stdout) if r.stdout else ("", [])
    entry = store.add_result("smi_q_x_after", r, text, redactions)
    return parsed if r.ok else {"$failure": cmd_failure_field(r, "smi_xml", entry["id"])}


def _delta(before: dict, after: dict | None, path: str) -> dict:
    b = model.get_path(before, path)
    a = model.get_path(after, path) if after else None
    if not after or not b or not a or b["status"] != "ok" or a["status"] != "ok":
        return missing("error", "derived", "no_before_after", None, "smi_q_x_after")
    return ok(a["value"] - b["value"], "derived", "smi_q_x_after")


def run_tests(probe, doc: dict, *, load_minutes: int, skip_dcgm: bool, gpus: list | None, say, before_bench=None) -> None:
    """Steps 2 to 5, then grade. before_bench runs between DCGM and the performance tests (the challenge)."""
    store = model.RawStore()

    # 2. DCGM
    if skip_dcgm:
        dcgm_fields = {g["index"]: dcgm.skipped("dcgm_skipped_by_user") for g in doc["gpus"]}
    else:
        say(T.DCGM_START)
        result, parsed, failure = dcgm.run(probe, gpus)
        dcgm_fields = {g["index"]: dcgm.fields(parsed, failure, g["index"]) for g in doc["gpus"]}
        say(T.DCGM_DONE if parsed else T.REASONS.get(failure["reason"], T.REASON_UNKNOWN))

    # 3. Challenge
    if before_bench:
        before_bench()

    # 4. Performance and load
    if probe.mock:
        from .bench.mockbench import MockBench

        log = bench.run_all(MockBench(probe.bench_data, probe.fixture), doc, load_minutes, say)
    elif _torch_ready(required=False):
        from .bench.torchbench import TorchBench

        log = bench.run_all(TorchBench(), doc, load_minutes, say)
    else:
        bench.skip_all(doc, "torch_missing")
        log = {"skipped": "torch_missing"}

    # 5. Errors during the test
    after = _after_test(probe, doc, store)
    for g in doc["gpus"]:
        a = after.get(g["card"]["uuid_sha256"]["value"] or "")
        pending = model.get_path(a, "history.row_remap.pending") if a else None
        g["diag"] = {
            **dcgm_fields[g["index"]],
            "ecc_uncorrectable_delta": _delta(g, a, "history.ecc.volatile.uncorrectable"),
            "ecc_correctable_delta": _delta(g, a, "history.ecc.volatile.correctable"),
            "row_remap_pending_after": dict(pending) if pending else missing("error", "derived", "no_before_after", None, None),
        }
    if not skip_dcgm:
        store.add_result("dcgm_diag", result, result.stdout)
    store.add("perf_log", "library", ["dud-bench"], json.dumps(log, indent=1, sort_keys=True))
    doc["raw"].extend(store.entries)
    grade.grade_doc(doc)


def run_full(args, probe, gpus) -> int:
    submit = not args.no_submit
    if submit and not api_url():
        print(T.REGISTRY_NOT_AVAILABLE)
        submit = False
    if submit and not load_credentials():
        raise DudError(T.NOT_LOGGED_IN)
    if not probe.mock:
        # CUDA must number GPUs like nvidia-smi and NVML. Use --gpus to select GPUs.
        os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
        os.environ.pop("CUDA_VISIBLE_DEVICES", None)
    if probe.mock:
        print(T.MOCK_BANNER)
    print(T.FULL_START.format(version=__version__))
    t0 = time.monotonic()
    options = {"gpus": gpus, "load_minutes": args.load_minutes, "skip_dcgm": args.skip_dcgm, "submit": submit}
    try:
        doc = collect(probe, mode="full", provider=args.provider, gpu_indices=gpus, options=options)
    except UnknownGpu as e:
        raise DudError(T.GPU_NOT_FOUND.format(missing=",".join(map(str, e.missing)),
                                              available=",".join(map(str, e.available)) or T.NONE))
    if not doc["gpus"]:
        raise DudError(T.NO_GPUS)
    if not probe.mock and not args.skip_dcgm:
        dcgm_install.offer(doc, print, assume_yes=getattr(args, "install_dcgm", False))
    client = Client() if submit else None

    def challenge_step():
        if client:
            doc["challenge"] = do_challenge(client, probe, doc)

    run_tests(probe, doc, load_minutes=args.load_minutes, skip_dcgm=args.skip_dcgm, gpus=gpus,
              say=print, before_bench=challenge_step)

    # 6. Save, send
    doc["run"]["finished_at"] = model.utc_now()
    doc["run"]["duration_s"] = round(time.monotonic() - t0, 3)
    folder = model.save_result(doc, Path(args.out_dir), report.render(doc))
    print()
    print(report.terminal_summary(doc))
    print()
    print(T.VERDICT_LINE.format(verdict=doc["node"]["verdict"]["verdict"], summary=doc["node"]["verdict"]["summary"]))
    print(T.RESULT_WRITTEN.format(path=folder / "result.json"))
    print(T.REPORT_WRITTEN.format(path=folder / "report.md"))
    if not client:
        print(T.SUBMIT_SKIPPED)
        return 0
    print(T.SUBMIT_START)
    try:
        resp = client.submit(doc)
    except RegistryError as e:
        print(T.SUBMIT_FAILED.format(detail=e))
        return 1
    (folder / "registry_response.json").write_text(json.dumps(resp, indent=2) + "\n")
    print(submit_message(resp))
    return 0 if resp.get("status") != "rejected" else 1


def submit_message(resp: dict) -> str:
    status = resp.get("status")
    if status == "accepted" and resp.get("grants_access"):
        return T.SUBMIT_ACCEPTED_ACCESS.format(date=(resp.get("access_until") or "")[:10])
    if status == "accepted":
        return T.SUBMIT_ACCEPTED_NO_ACCESS.format(reason=resp.get("reason"))
    details = "; ".join(f"{c['name']}: {c['detail']}" for c in resp.get("checks", []) if c.get("result") != "pass")
    if status == "flagged":
        return T.SUBMIT_FLAGGED.format(reason=details or resp.get("reason"))
    return T.SUBMIT_REJECTED.format(reason=details or resp.get("reason"))
