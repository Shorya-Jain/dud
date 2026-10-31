#!/usr/bin/env python3
"""Admin tool for the dud registry. Only the registry owner uses it.

Set these first:
    export DUD_API_URL=https://dud-registry.<your-subdomain>.workers.dev
    export DUD_ADMIN_TOKEN=<the ADMIN_TOKEN secret>

Examples:
    python3 admin/dud_admin.py flags
    python3 admin/dud_admin.py submissions --status flagged
    python3 admin/dud_admin.py show sub_0123abcd
    python3 admin/dud_admin.py document sub_0123abcd --out sub.json
    python3 admin/dud_admin.py decide sub_0123abcd accept --note "Known contributor"
    python3 admin/dud_admin.py account octocat
    python3 admin/dud_admin.py quarantine octocat --note "Readings disagree with 3 other accounts"
    python3 admin/dud_admin.py unquarantine octocat --note "Checked"
    python3 admin/dud_admin.py revoke octocat --note "Token shared in a public repository"
    python3 admin/dud_admin.py resolve-flag 12 --note "False alarm"
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def call(method, path, body=None, raw=False):
    base = os.environ.get("DUD_API_URL", "").rstrip("/")
    token = os.environ.get("DUD_ADMIN_TOKEN", "")
    if not base or not token:
        sys.exit("Set DUD_API_URL and DUD_ADMIN_TOKEN.")
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"authorization": f"Bearer {token}", "content-type": "application/json", "user-agent": "dud-admin"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            return data if raw else json.loads(data)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode(errors='replace')}")


def show(obj):
    print(json.dumps(obj, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="dud_admin", description="Admin tool for the dud registry.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("flags", help="Show open admin flags.")
    s = sub.add_parser("submissions", help="List submissions by status.")
    s.add_argument("--status", default="flagged", choices=["flagged", "accepted", "rejected"])
    s = sub.add_parser("show", help="Show one submission and the log of its checks.")
    s.add_argument("id")
    s = sub.add_parser("document", help="Download the full result file of a submission.")
    s.add_argument("id")
    s.add_argument("--out", required=True)
    s = sub.add_parser("decide", help="Accept or reject a flagged submission.")
    s.add_argument("id")
    s.add_argument("decision", choices=["accept", "reject"])
    s.add_argument("--note", required=True)
    s = sub.add_parser("account", help="Show an account (ID or GitHub login).")
    s.add_argument("account")
    for name, text in (("quarantine", "Stop an account: no access, readings not shown."),
                       ("unquarantine", "Start a stopped account again."),
                       ("revoke", "Stop the token of an account. The user must run dud login again.")):
        s = sub.add_parser(name, help=text)
        s.add_argument("account")
        s.add_argument("--note", required=True)
    s = sub.add_parser("resolve-flag", help="Close an admin flag.")
    s.add_argument("id")
    s.add_argument("--note", required=True)
    a = p.parse_args(argv)

    if a.cmd == "flags":
        show(call("GET", "/v1/admin/flags"))
    elif a.cmd == "submissions":
        show(call("GET", f"/v1/admin/submissions?status={a.status}"))
    elif a.cmd == "show":
        show(call("GET", f"/v1/admin/submissions/{a.id}"))
    elif a.cmd == "document":
        with open(a.out, "wb") as f:
            f.write(call("GET", f"/v1/admin/submissions/{a.id}/document", raw=True))
        print(f"Wrote {a.out}")
    elif a.cmd == "decide":
        show(call("POST", f"/v1/admin/submissions/{a.id}/decision", {"decision": a.decision, "note": a.note}))
    elif a.cmd == "account":
        show(call("GET", f"/v1/admin/accounts/{a.account}"))
    elif a.cmd in ("quarantine", "unquarantine"):
        show(call("POST", f"/v1/admin/accounts/{a.account}/quarantine", {"on": a.cmd == "quarantine", "note": a.note}))
    elif a.cmd == "revoke":
        show(call("POST", f"/v1/admin/accounts/{a.account}/revoke", {"note": a.note}))
    elif a.cmd == "resolve-flag":
        show(call("POST", f"/v1/admin/flags/{a.id}/resolve", {"note": a.note}))


if __name__ == "__main__":
    main()
