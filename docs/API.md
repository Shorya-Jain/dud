# Registry API

All requests and answers are JSON.
The base address is the Worker address, for example `https://dud-registry.your-name.workers.dev`.
Requests that need a login send the header `Authorization: Bearer dud_...`.

An error answer has this form. `message` is for people and is in Simplified Technical English.

```json
{"error": "no_access", "message": "You do not have registry access. Run dud full and send the result. ..."}
```

| HTTP status | Meaning |
|---|---|
| 400 | The request is not correct. |
| 401 | No token, a token that is not valid, or a stopped token. |
| 403 | The account has no registry access. |
| 404 | Not found. Also for every path that is not in this list. |
| 409 | The challenge is not ready for this step. |
| 410 | The challenge expired. |
| 413 | The body is too large. |
| 422 | A challenge check failed, or the registry rejected a submission. |
| 429 | Daily quota or daily limit. |

## Public

### `GET /v1/config`

Returns `{github_client_id, access_days, schema_version}`. `dud login` uses the client ID.

## Login (no access needed)

### `POST /v1/auth/github`

Body: `{"github_token": "<GitHub OAuth token from the device flow>"}`.
The registry checks that the token belongs to the dud OAuth app, reads the GitHub user, then revokes the GitHub token.
It makes one dud account per GitHub account, and returns a new dud token. The old dud token of the account stops.

Answer: `{token, account: {id, github_login, access_until, has_access, trust, status, new_github_account}}`.

### `GET /v1/me`

Answer: `{account, lookups_today, lookup_quota}`.

## Challenge (login needed, no access needed)

### `POST /v1/challenges`

Body: `{"gpus": [{"gpu_index": 0, "card_id": "<64 hex>", "model_key": "H100-SXM5-80GB"}]}` (1 to 16 GPUs).

Answer:

```json
{"challenge_id": "chl_...", "nonce": "<64 hex>", "issued_at": "...", "expires_at": "...",
 "rounds": [{"gpu_index": 0, "seed": 123, "params": {"m": 1024, "n": 1024, "k": 16384, "pool": 8, "batch": 32}, "count": 431000}]}
```

The server clock starts now.

### `POST /v1/challenges/{id}/commit`

Body: `{"roots": [{"gpu_index": 0, "merkle_root": "<64 hex>"}]}`.
The server measures the time since the challenge started. It must be inside the limits for the model.

Answer: `{status: "committed", elapsed_ms, samples: [{gpu_index, j}], reveal_deadline}`.

### `POST /v1/challenges/{id}/reveal`

One request for each sample:
`{"gpu_index": 0, "j": 12345, "digest": 4011223344, "proof": ["<64 hex>", ...], "product_b64": "<m*n int16, little-endian, base64>"}`.

Answer: `{status: "committed" | "verified", remaining}`.

## Submission (login needed, no access needed)

### `POST /v1/submissions`

Body: a full-test result file (`src/dud/schema/result.v1.json`). `challenge.challenge_id` and `challenge.nonce` must be from a verified challenge.

Answer (HTTP 200, or 422 if rejected):

```json
{"submission_id": "sub_...", "status": "accepted", "grants_access": true, "access_until": "...",
 "reason": "all checks passed", "checks": [{"name": "access", "result": "pass", "detail": "gives access"}]}
```

`checks` lists every check that did not pass, and the access check. The full log is in the table `submission_checks`.

## Registry reads (access needed, each counts against the daily quota)

### `GET /v1/cards/{card_id}`

`card_id` is the SHA-256 of the GPU UUID (64 hexadecimal characters).
Answer: `{card_id, contributors, readings: [...], lookups_left_today}`. Only accepted readings from active accounts.
Each reading has `verdict` (KEEP, KILL or UNKNOWN), calculated by the registry, and `verdict_reasons` (the text of each rule that failed or had no value).

### `GET /v1/stats/{model_key}?provider=<name>`

Answer: `{model_key, provider, enough_data, percentiles: {<value>: {p10, p50, p90}}, lookups_left_today}`.
`enough_data` is false when there are fewer than `STATS_MIN_CARDS` cards or fewer than 1 / `CONTRIBUTOR_CAP` contributors.

## Admin (`Authorization: Bearer <ADMIN_TOKEN>`)

| Method and path | Use |
|---|---|
| `GET /v1/admin/flags` | Open admin flags |
| `POST /v1/admin/flags/{id}/resolve` | Close a flag. Body `{note}` |
| `GET /v1/admin/submissions?status=flagged` | List submissions |
| `GET /v1/admin/submissions/{id}` | One submission, its checks and its account |
| `GET /v1/admin/submissions/{id}/document` | The full result file from R2 |
| `POST /v1/admin/submissions/{id}/decision` | Body `{decision: "accept" or "reject", note}`. Flagged submissions only |
| `GET /v1/admin/accounts/{id or login}` | Account, submissions, networks, tokens |
| `POST /v1/admin/accounts/{id or login}/quarantine` | Body `{on: true or false, note}` |
| `POST /v1/admin/accounts/{id or login}/revoke` | Stop the token. Body `{note}` |
