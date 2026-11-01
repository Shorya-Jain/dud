"""The `dud` command."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, grade, history, model, report
from . import text as T
from .collect import UnknownGpu, collect
from .model import DudError
from .probe import get_probe
from .registry import Client, api_url, delete_credentials, github_device_flow, load_credentials, save_credentials


def parse_gpus(value: str | None) -> list | None:
    if value is None:
        return None
    try:
        out = sorted({int(x) for x in value.split(",") if x.strip()})
    except ValueError:
        raise DudError(T.BAD_GPUS_FLAG)
    if not out or out[0] < 0:
        raise DudError(T.BAD_GPUS_FLAG)
    return out


def cmd_quick(args) -> int:
    probe = get_probe()
    if probe.mock:
        print(T.MOCK_BANNER)
    print(T.QUICK_START.format(version=__version__))
    gpus = parse_gpus(args.gpus)
    options = {"gpus": gpus, "load_minutes": None, "skip_dcgm": False, "submit": False}
    try:
        doc = collect(probe, mode="quick", provider=args.provider, gpu_indices=gpus, options=options)
    except UnknownGpu as e:
        raise DudError(T.GPU_NOT_FOUND.format(missing=",".join(map(str, e.missing)),
                                              available=",".join(map(str, e.available)) or T.NONE))
    if not args.offline and doc["gpus"]:
        doc["registry"] = history.fetch(doc)
        history.compare(doc)
    if doc["gpus"]:
        grade.grade_doc(doc)
    folder = model.save_result(doc, Path(args.out_dir), report.render(doc))
    print()
    if doc["gpus"]:
        print(report.terminal_summary(doc))
        print()
        for line in report.registry_lines(doc):
            print(line)
        for gpu in doc["gpus"]:
            print(T.GPU_VERDICT_LINE.format(index=gpu["index"], verdict=gpu["verdict"]["verdict"], summary=gpu["verdict"]["summary"]))
    else:
        print(T.NO_GPUS)
    print()
    print(T.RESULT_WRITTEN.format(path=folder / "result.json"))
    print(T.REPORT_WRITTEN.format(path=folder / "report.md"))
    print(T.RAW_WRITTEN.format(path=folder / "raw"))
    return 0 if doc["gpus"] else 1


def cmd_full(args) -> int:
    from .fulltest import run_full

    if args.load_minutes < 1:
        raise DudError(T.BAD_LOAD_MINUTES)
    return run_full(args, get_probe(), parse_gpus(args.gpus))


def cmd_report(args) -> int:
    text = report.render(model.load_result(Path(args.file)))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(T.REPORT_WRITTEN.format(path=args.out))
    else:
        print(text)
    return 0


def cmd_login(args) -> int:
    client = Client(token="")
    client_id = client.config()["github_client_id"]

    def show(code, uri):
        print(T.LOGIN_OPEN.format(uri=uri))
        print(T.LOGIN_CODE.format(code=code))
        print(T.LOGIN_WAIT)

    github_token = github_device_flow(client_id, show)
    resp = client.login(github_token)
    path = save_credentials(client.base, resp["token"], resp["account"]["github_login"])
    print(T.LOGIN_DONE.format(login=resp["account"]["github_login"], path=path))
    if resp["account"].get("new_github_account"):
        print(T.LOGIN_NEW_ACCOUNT)
    return 0


def cmd_logout(args) -> int:
    print(T.LOGOUT_DONE if delete_credentials() else T.LOGOUT_NONE)
    return 0


def cmd_status(args) -> int:
    if not load_credentials():
        raise DudError(T.NOT_LOGGED_IN)
    me = Client().me()
    a = me["account"]
    print(T.STATUS_ACCOUNT.format(login=a["github_login"], url=api_url()))
    print(T.STATUS_ACCESS.format(date=a["access_until"][:10]) if a["has_access"] else T.STATUS_NO_ACCESS)
    print(T.STATUS_LOOKUPS.format(used=me["lookups_today"], quota=me["lookup_quota"]))
    if a["status"] != "active":
        print(T.STATUS_QUARANTINED)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dud", description=T.HELP["description"])
    p.add_argument("--version", action="version", version=f"dud {__version__}")
    sub = p.add_subparsers(dest="command")

    def common(sp):
        sp.add_argument("--provider", help=T.HELP["provider"])
        sp.add_argument("--gpus", help=T.HELP["gpus"])
        sp.add_argument("--out-dir", default="dud-results", help=T.HELP["out_dir"])

    quick = sub.add_parser("quick", help=T.HELP["quick"])
    common(quick)
    quick.add_argument("--offline", action="store_true", help=T.HELP["offline"])
    quick.set_defaults(func=cmd_quick)

    full = sub.add_parser("full", help=T.HELP["full"])
    common(full)
    full.add_argument("--no-submit", action="store_true", help=T.HELP["no_submit"])
    full.add_argument("--skip-dcgm", action="store_true", help=T.HELP["skip_dcgm"])
    full.add_argument("--install-dcgm", action="store_true", help=T.HELP["install_dcgm"])
    full.add_argument("--load-minutes", type=int, default=15, help=T.HELP["load_minutes"])
    full.set_defaults(func=cmd_full)

    sub.add_parser("login", help=T.HELP["login"]).set_defaults(func=cmd_login)
    sub.add_parser("logout", help=T.HELP["logout"]).set_defaults(func=cmd_logout)
    sub.add_parser("status", help=T.HELP["status"]).set_defaults(func=cmd_status)

    rep = sub.add_parser("report", help=T.HELP["report"])
    rep.add_argument("file", help=T.HELP["report_file"])
    rep.add_argument("--out", help=T.HELP["report_out"])
    rep.set_defaults(func=cmd_report)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except DudError as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(T.STOPPED, file=sys.stderr)
        return 130
