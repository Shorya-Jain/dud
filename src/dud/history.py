"""Registry history for `dud quick`: get earlier readings of each card and compare."""
from __future__ import annotations

from . import model
from . import text as T
from .registry import Client, RegistryError, api_url, load_credentials

# Aggregate counters only go up. A lower value now than in the registry is a finding.
COUNTERS = [
    ("history.ecc.aggregate.correctable", "aggregate_correctable", "ecc"),
    ("history.ecc.aggregate.uncorrectable", "aggregate_uncorrectable", "ecc"),
    ("history.row_remap.correctable", "correctable", "row_remap"),
    ("history.row_remap.uncorrectable", "uncorrectable", "row_remap"),
]


def fetch(doc: dict, client: Client | None = None) -> dict:
    """Return the registry section of a quick-test result."""
    out = {"api_url": api_url(), "checked_at": model.utc_now(), "status": "ok", "message": None, "cards": {}}
    if client is None:
        if not api_url():
            return dict(out, status="no_registry", message=T.REGISTRY_NOT_AVAILABLE)
        if not load_credentials():
            return dict(out, status="not_logged_in", message=T.REGISTRY_NOT_LOGGED_IN)
        client = Client()
    for gpu in doc["gpus"]:
        card = gpu["card"]["uuid_sha256"]
        if card["status"] != "ok":
            continue
        try:
            out["cards"][card["value"]] = client.card(card["value"])
        except RegistryError as e:
            status = {401: "not_logged_in", 403: "no_access", 429: "quota"}.get(e.status, "error")
            return dict(out, status=status, message=str(e))
    return out


def compare(doc: dict) -> None:
    """Add a finding where a counter is lower now than in an earlier registry reading."""
    reg = doc.get("registry") or {}
    for gpu in doc["gpus"]:
        data = reg.get("cards", {}).get(gpu["card"]["uuid_sha256"]["value"] or "")
        if not data:
            continue
        for path, key, group in COUNTERS:
            now = model.get_path(gpu, path)
            earlier = [r[group][key] for r in data["readings"] if r[group][key] is not None]
            if now and now["status"] == "ok" and earlier and now["value"] < max(earlier):
                gpu["findings"].append({"code": "counter_lower_than_registry", "severity": "warn", "path": path,
                                        "detail": f"now={now['value']} registry_max={max(earlier)}"})
