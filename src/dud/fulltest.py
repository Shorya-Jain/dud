"""`dud full`: collect, do the registry challenge, then submit.

Milestone 2 adds DCGM, the performance tests and the load test between the
challenge and the submission.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, challenge, model, report
from . import text as T
from .collect import UnknownGpu, collect
from .model import DudError
from .registry import Client, RegistryError, load_credentials


def _gpus_for_challenge(doc: dict) -> list:
    out = []
    for g in doc["gpus"]:
        card, key = g["card"]["uuid_sha256"], g["identity"]["model_key"]
        if card["status"] != "ok" or key["status"] != "ok":
            raise DudError(T.CARD_ID_MISSING.format(index=g["index"]))
        out.append({"gpu_index": g["index"], "card_id": card["value"], "model_key": key["value"]})
    return out


def _ensure_torch():
    try:
        import torch  # noqa: F401
        return
    except ImportError:
        pass
    command = f"{sys.executable} -m pip install torch"
    print(T.TORCH_MISSING.format(command=command))
    if not sys.stdin.isatty() or input(T.TORCH_ASK).strip().lower() not in ("y", "yes"):
        raise DudError(T.TORCH_NOT_INSTALLED)
    if subprocess.call(command.split()) != 0:
        raise DudError(T.TORCH_NOT_INSTALLED)


def _runners(probe, gpu_indices: list) -> dict:
    if probe.mock:
        runners = {i: challenge.ReferenceRunner() for i in gpu_indices}
    else:
        _ensure_torch()
        import torch

        if not torch.cuda.is_available():
            raise DudError(T.TORCH_NO_CUDA)
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
    return {
        "challenge_id": created["challenge_id"],
        "nonce": created["nonce"],
        "issued_at": created["issued_at"],
        "rounds": [{"gpu_index": g["gpu_index"], "card_id": g["card_id"], "model_key": g["model_key"],
                    "count": rounds[g["gpu_index"]]["count"], "merkle_root": by_gpu[g["gpu_index"]]} for g in gpus],
        "client_elapsed_s": state["elapsed_s"],
        "server_elapsed_ms": committed["elapsed_ms"],
        "samples": committed["samples"],
    }


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


def run_full(args, probe, gpus) -> int:
    submit = not args.no_submit
    if submit and not load_credentials():
        raise DudError(T.NOT_LOGGED_IN)
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

    client = Client() if submit else None
    if client:
        doc["challenge"] = do_challenge(client, probe, doc)
    print(T.FULL_NOT_YET)

    doc["run"]["finished_at"] = model.utc_now()
    doc["run"]["duration_s"] = round(time.monotonic() - t0, 3)
    folder = model.save_result(doc, Path(args.out_dir), report.render(doc))
    print()
    print(report.terminal_summary(doc))
    print()
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
