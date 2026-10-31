# dud design record

This file records the decisions behind the data model and the registry.
Read it before you change the schema, the challenge or a registry check.
`THREATS.md` gives the threats that each check stops.

## Parts

| Part | Where | Language |
|---|---|---|
| CLI (`dud`) | `src/dud/` | Python 3.9+, standard library and nvidia-ml-py. PyTorch only for the full-test challenge |
| Result schema | `src/dud/schema/result.v1.json` | JSON Schema. The CLI tests and the registry both use it |
| Datasheet values | `specs.yaml` (server copy: `server/src/specs.json`) | YAML |
| Registry | `server/src/` | TypeScript, Cloudflare Workers, D1, R2 |
| Admin tool | `admin/dud_admin.py` | Python, standard library |

## Result document (schema version 1)

- **Field**: every reading is `{value, status, source, raw_ref, reason, detail}`.
  - `status` is `ok`, `blocked`, `not_supported`, `error` or `skipped`. `value` is null unless status is `ok`.
  - `reason` is a code (for example `hidden_on_supported_model`). `src/dud/text.py` has the text for each code.
  - The visibility map in the report comes from these Fields. It cannot disagree with the values.
- **Raw output**: each entry has the text after redaction (gzip, base64), its SHA-256 and its size. The SHA-256 is of the UTF-8 text before compression.
- **Sections that later milestones fill**: `diag`, `perf`, `load`, `verdict` and `node.p2p_bandwidth` (milestone 2), `attestation` (future). They are null now. Filling them needs no schema version change.
- **`challenge`**: the challenge transcript of a full test (ID, nonce, Merkle roots, samples, times).
- **`registry`**: optional, quick test only. Earlier registry readings of the cards. The registry ignores it.
- **`gpu.load`** (milestone 2 fills it, the registry checks it now):
  `{interval_s, minutes, series: {t_s, sm_clock_mhz, mem_clock_mhz, temp_c, power_w, util_pct, throttle_mask}}`, one value per sample in each list.
- Increase `schema_version` only when an old reader cannot read the new document.

## Card IDs (frozen)

- Card ID = SHA-256 of `"dud-card-v1:uuid:" + lower(trim(UUID))`.
- Serial ID = SHA-256 of `"dud-card-v1:serial:" + upper(trim(serial))`.
- `tests/test_ids.py` freezes both with fixed values. If you must change the scheme, add `dud-card-v2` and keep v1.
- The registry stores HMAC-SHA256(`CARD_ID_PEPPER`, `"card:" + card ID`) and the same for serial IDs. Never change the pepper.
- Registry lookups accept the card ID only, never the serial ID.

## Privacy

- Before any raw output is stored, `ids.redact_smi_xml` replaces `<uuid>` and every `<*serial*>` element with a hash marker. It also removes `<processes>` lists.
- Then `RawStore.scrub` replaces every known UUID and serial anywhere in any raw output.
- The kernel log keeps XID lines only, without `pid=` and `name=`.
- The registry rejects XML that contains a raw UUID.

## Sources

- The `nvidia-smi -q -x` XML is the main evidence, because the registry can read it again and compare.
- NVML gives no raw text to check. dud uses NVML to fill values that the XML does not include, and as a cross-check.
- On a known data center model (`gpumodels.py`), N/A for ECC or row remap values means `blocked`. If ECC mode is disabled, the reason is `ecc_disabled`. On A100 and later, retired pages are `not_supported`.

## Challenge

The challenge proves that a GPU of approximately the claimed speed did fresh work in a time that the server measures.
Code: `src/dud/challenge.py` (client, PyTorch and a pure-Python reference) and `server/src/chalmath.ts` (server).
`fixtures/challenge_vectors.json` makes sure that both give the same numbers.

1. The client sends the card IDs and model keys. The server makes a nonce and, for each GPU, `seed = first 4 bytes of SHA-256("dud-challenge-v1:<nonce>:<card ID>")`.
2. For each GPU, the server sets the size from `specs.yaml`. The number of products is
   `count = target_seconds × FP16 rate × assumed_efficiency / (2·m·n·k)`.
3. The client makes a pool of `pool` A matrices (m×k) and B matrices (k×n) from the seed. Entries are -1, 0 or 1 from a 32-bit hash (`mix32`).
4. Product j is `C_j = (A[a_j] ⊙ t_j) · B[b_q]`:
   - `t_j` is a ±1 vector from the seed. It makes each product different, so the client cannot use one result again.
   - `q = j // batch`, so one GPU call does `batch` products with one B.
   - FP16 tensor cores with FP32 accumulation give exact integers. |C| stays far below 2048.
5. `digest_j = Σ mix32((C_j[i,c] + 32768) XOR key[i,c] XOR salt_j) mod 2^32`. The function is not linear, so the client must have every entry of C_j.
6. The client builds a Merkle tree over the digests and sends the roots. The server notes the time since step 1 and checks it against the model limits:
   - Minimum: `count × 2mnk / FP16 rate`. Faster is impossible.
   - Maximum: the same at `min_efficiency`, plus `network_allowance_seconds`.
7. The server picks `samples_per_gpu` products at random. For each one, the client sends C_j, digest_j and a Merkle proof. The server checks three things:
   - The proof matches the root.
   - The digest matches C_j.
   - C_j is correct (Freivalds test: `C·r = A'·(B·r)` for a random r with 16-bit entries, exact in float64).
8. When all samples pass, the challenge is `verified`. A submission can use it one time, before it expires (3 hours).

Why not "BF16 matrices seeded with the nonce, and a hash of the output"?
A plain hash of the output lets a client send any hash and then compute only the entries that the server asks for.
Random BF16 values also make exact checks on the server hard.
The Merkle commit over all digests, and exact integer products, close both problems.

To calibrate: run real full tests on each model and record `server_elapsed_ms`. Then set `min_efficiency` (and `assumed_efficiency`) in `specs.yaml` so that honest runs pass with a margin and slower GPUs fail.

## Registry

### Storage

- D1 (`server/migrations/0001_init.sql`):
  - People: `accounts`, `tokens` (SHA-256 only).
  - Tests: `challenges`, `submissions`, `submission_checks` (the log of every check).
  - Cards: `cards`, `readings` (one row for each GPU in each submission), `raw_hashes`, `card_unlocks`.
  - Abuse defenses: `daily_usage`, `request_networks`, `admin_flags`, `audit_log`.
- R2 (private): `submissions/<submission ID>.json.gz`, the full result file with all raw output.

### Submission checks, in sequence (`server/src/submit.ts`)

| Check | Fail result |
|---|---|
| `schema`: the document matches result.v1.json | reject |
| `mode`: full test, not mock | reject |
| `challenge`: own, verified, not used, not expired, same nonce | reject |
| `card_ids`: the same GPUs and models as the challenge | reject |
| `raw_hashes`: each raw output decodes and matches its SHA-256 and size | reject |
| `replay`: no raw output that an earlier submission had | reject |
| `parsed_values`: values match the server's own reading of the XML | reject |
| `specs`: model key, memory and default power limit match `specs.yaml` | reject |
| `timing`: start, finish, duration, challenge time and nvidia-smi time agree | reject (flag if the time cannot be checked) |
| `load`: a load series exists (if `REQUIRE_LOAD`) and is physically possible | reject |
| `counters`: no aggregate counter lower than an earlier reading of the card | flag |
| `account`: active account, GitHub account at least 30 days old | flag |
| `access`: all GPUs tested, and no card gave access to another account in 30 days | no access (the data is still accepted) |

Any reject: the submission is `rejected`. Else any flag: `flagged` (stored, no access, admin review). Else `accepted`.

### Access

- An accepted submission that passes `access` sets `access_until = now + ACCESS_DAYS`.
- Each lookup and each stats request counts against `DAILY_LOOKUP_QUOTA`. The count goes up before the data goes out.
- Quarantined accounts have no access, and their readings are not shown.

### Trust

- New accounts start at trust 0.2. Lookups mark readings from trust below 0.5 as "low".
- After each accepted submission, the registry compares the readings with other contributors' accepted readings of the same cards. The model and memory must match, and counters must be in time order. Agree: +0.05. Disagree: -0.2 and an admin flag.
- Stats use the latest accepted reading of each card, weighted by trust. One contributor has at most `CONTRIBUTOR_CAP` of the weight.

## Decisions from the owner

31 Oct 2026, milestone 1:

- Registry server: TypeScript on Cloudflare Workers.
- API address: `*.workers.dev` for now. `DUD_API_URL` overrides the address in the CLI.
- An aggregate counter that is lower than an earlier reading of the same card: flag, keep, no access, admin review.
- `dud quick` does not send readings to the registry in v1.
- Package name on PyPI: `dud-gpu` (`dud` is taken). The command is `dud`.

31 Oct 2026, milestone 3:

- The registry came before milestone 2. `REQUIRE_LOAD` is off until the CLI has the load test. Turn it on before launch.
- The challenge uses exact FP16 integer products and a Merkle commit. See "Challenge" above.
- A submission gives access only if it tests all GPUs on the node.
- If any GPU in a submission gave access to another account in the last 30 days, the submission gives no access.
- Quarantined accounts lose access.

## Values to check against real output

These come from the known format, not from a real GPU. Check them when real fixtures arrive.

- Product names in `gpumodels.py` (and `server/src/models.ts`), mainly H200 and H100 NVL.
- XML element names for bank availability (`remapped_row_histogram/row_remap_histogram_*`).
- The number of banks in the fixtures (2560 for H100, 640 for A100). These are placeholders.
- NVML memory total versus nvidia-smi `fb_memory_usage/total`.
- All values with `verify: true` in `specs.yaml`.
- The challenge time limits (`min_efficiency`).
