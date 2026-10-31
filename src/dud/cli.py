"""The `dud` command."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, model, report
from . import text as T
from .collect import UnknownGpu, collect
from .model import DudError
from .probe import get_probe


def parse_gpus(value: str | None) -> list | None:
    if value is None:
        return None
    try:
        out = sorted({int(x) for x in value.split(",") if x.strip()})
    except ValueError:
        raise DudError(T.BAD_GPUS_FLAG)
    if not out:
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
    folder = model.save_result(doc, Path(args.out_dir), report.render(doc))
    print()
    if doc["gpus"]:
        print(report.terminal_summary(doc))
    else:
        print(T.NO_GPUS)
    print()
    print(T.RESULT_WRITTEN.format(path=folder / "result.json"))
    print(T.REPORT_WRITTEN.format(path=folder / "report.md"))
    print(T.RAW_WRITTEN.format(path=folder / "raw"))
    return 0 if doc["gpus"] else 1


def cmd_report(args) -> int:
    text = report.render(model.load_result(Path(args.file)))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(T.REPORT_WRITTEN.format(path=args.out))
    else:
        print(text)
    return 0


def cmd_not_in_version(args) -> int:
    print(T.COMMAND_NOT_IN_VERSION.format(name=args.command), file=sys.stderr)
    return 2


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
    quick.set_defaults(func=cmd_quick)

    full = sub.add_parser("full", help=T.HELP["full"])
    common(full)
    full.add_argument("--no-submit", action="store_true", help=T.HELP["no_submit"])
    full.add_argument("--skip-dcgm", action="store_true", help=T.HELP["skip_dcgm"])
    full.add_argument("--load-minutes", type=int, default=15, help=T.HELP["load_minutes"])
    full.set_defaults(func=cmd_not_in_version)

    login = sub.add_parser("login", help=T.HELP["login"])
    login.set_defaults(func=cmd_not_in_version)

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
