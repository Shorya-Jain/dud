"""Registry API client and the saved login (~/.dud/credentials.json).

Python standard library only, so that dud installs fast on rented nodes.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import __version__
from . import text as T
from .model import DudError

# The registry (docs/DEPLOY.md, step 8). Use only an address that you own:
# dud sends tokens and results to it. None: no registry.
# DUD_API_URL in the environment overrides it.
DEFAULT_API_URL: str | None = "https://dud-registry.shoryajain99.workers.dev"

GITHUB_DEVICE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"


class RegistryError(DudError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body or {}


# --- Saved login -----------------------------------------------------------------

def dud_home() -> Path:
    return Path(os.environ.get("DUD_HOME") or Path.home() / ".dud")


def credentials_path() -> Path:
    return dud_home() / "credentials.json"


def load_credentials() -> dict | None:
    if os.environ.get("DUD_TOKEN"):
        return {"token": os.environ["DUD_TOKEN"], "api_url": None, "github_login": None}
    try:
        return json.loads(credentials_path().read_text())
    except (OSError, ValueError):
        return None


def save_credentials(api_url: str, token: str, github_login: str) -> Path:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"api_url": api_url, "token": token, "github_login": github_login,
                   "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    os.replace(tmp, path)
    return path


def delete_credentials() -> bool:
    try:
        credentials_path().unlink()
        return True
    except FileNotFoundError:
        return False


def api_url() -> str | None:
    """The registry address, or None if there is no registry yet."""
    if os.environ.get("DUD_API_URL"):
        return os.environ["DUD_API_URL"].rstrip("/")
    creds = load_credentials()
    if creds and creds.get("api_url"):
        return creds["api_url"].rstrip("/")
    return DEFAULT_API_URL


# --- HTTP ------------------------------------------------------------------------------

def _request(method: str, url: str, body=None, headers=None, form: bool = False, timeout: int = 120):
    data = None
    h = {"user-agent": f"dud/{__version__}", "accept": "application/json"}
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            h["content-type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            h["content-type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RegistryError(T.REGISTRY_UNREACHABLE.format(url=url.split("/v1/")[0], detail=getattr(e, "reason", e)))


class Client:
    def __init__(self, base: str | None = None, token: str | None = None):
        base = base or api_url()
        if not base:
            raise RegistryError(T.REGISTRY_NOT_AVAILABLE, code="no_registry")
        self.base = base.rstrip("/")
        if token is None:
            creds = load_credentials()
            token = creds["token"] if creds else None
        self.token = token

    def call(self, method: str, path: str, body=None, auth: bool = True, ok=(200,), timeout: int = 120) -> dict:
        headers = {}
        if auth:
            if not self.token:
                raise RegistryError(T.NOT_LOGGED_IN, status=401, code="unauthorized")
            headers["authorization"] = f"Bearer {self.token}"
        status, payload = _request(method, self.base + path, body, headers, timeout=timeout)
        if status not in ok:
            raise RegistryError(payload.get("message") or T.REGISTRY_ERROR.format(status=status),
                                status=status, code=payload.get("error"), body=payload)
        return payload

    def config(self) -> dict:
        return self.call("GET", "/v1/config", auth=False)

    def login(self, github_token: str) -> dict:
        return self.call("POST", "/v1/auth/github", {"github_token": github_token}, auth=False)

    def me(self) -> dict:
        return self.call("GET", "/v1/me")

    def create_challenge(self, gpus: list) -> dict:
        return self.call("POST", "/v1/challenges", {"gpus": gpus})

    def commit(self, challenge_id: str, roots: list) -> dict:
        return self.call("POST", f"/v1/challenges/{challenge_id}/commit", {"roots": roots})

    def reveal(self, challenge_id: str, body: dict) -> dict:
        return self.call("POST", f"/v1/challenges/{challenge_id}/reveal", body, timeout=600)

    def submit(self, doc: dict) -> dict:
        return self.call("POST", "/v1/submissions", doc, ok=(200, 422), timeout=600)

    def card(self, card_id: str) -> dict:
        return self.call("GET", f"/v1/cards/{card_id}")

    def stats(self, model_key: str, provider: str | None = None) -> dict:
        q = f"?provider={urllib.parse.quote(provider)}" if provider else ""
        return self.call("GET", f"/v1/stats/{model_key}{q}")


# --- GitHub device flow ------------------------------------------------------------------

def github_device_flow(client_id: str, show, post=None, sleep=time.sleep) -> str:
    """Return a GitHub access token. `show(user_code, verification_uri)` tells the user what to do."""
    post = post or (lambda url, body: _request("POST", url, body, form=True, timeout=30))
    status, start = post(GITHUB_DEVICE_URL, {"client_id": client_id, "scope": ""})
    if status != 200 or "device_code" not in start:
        raise RegistryError(T.GITHUB_DEVICE_FAILED.format(detail=start.get("error_description") or start.get("error") or status))
    show(start["user_code"], start["verification_uri"])
    interval = int(start.get("interval", 5))
    deadline = time.monotonic() + int(start.get("expires_in", 900))
    while time.monotonic() < deadline:
        sleep(interval)
        _, r = post(GITHUB_TOKEN_URL, {"client_id": client_id, "device_code": start["device_code"],
                                       "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        if "access_token" in r:
            return r["access_token"]
        error = r.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = int(r.get("interval", interval + 5))
            continue
        if error == "access_denied":
            raise RegistryError(T.GITHUB_DENIED)
        raise RegistryError(T.GITHUB_DEVICE_FAILED.format(detail=r.get("error_description") or error))
    raise RegistryError(T.GITHUB_EXPIRED)
