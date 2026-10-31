# dud design record

This file records the decisions behind the data model. Read it before you change the schema.

## Result document (schema version 1)

- Contract: `src/dud/schema/result.v1.json`. Tests validate every fixture against it. The registry (milestone 3) validates every submission against it.
- **Field**: every reading is `{value, status, source, raw_ref, reason, detail}`.
  - `status` is `ok`, `blocked`, `not_supported`, `error` or `skipped`. `value` is null unless status is `ok`.
  - `reason` is a code (for example `hidden_on_supported_model`). `src/dud/text.py` has the text for each code.
  - The visibility map in the report comes from these Fields. It cannot disagree with the values.
- **Raw output**: each entry has the text after redaction (gzip, base64), its SHA-256 and its size. The SHA-256 is of the UTF-8 text before compression. The registry uses it to find duplicate submissions.
- **Reserved sections**: `diag`, `perf`, `load`, `verdict`, `node.p2p_bandwidth`, `challenge` and `attestation` are null in milestone 1. Later milestones fill them without a schema version change.
- Increase `schema_version` only when an old reader cannot read the new document.

## Card IDs (frozen)

- Card ID = SHA-256 of `"dud-card-v1:uuid:" + lower(trim(UUID))`.
- Serial ID = SHA-256 of `"dud-card-v1:serial:" + upper(trim(serial))`.
- `tests/test_ids.py` freezes both with fixed values. If you must change the scheme, add `dud-card-v2` and keep v1.
- The registry stores an HMAC of these hashes with a server secret (milestone 3). Serial numbers are short and in sequence, so a plain hash can be reversed by trying all serials.
- Registry lookups accept the card ID (UUID) only, never the serial ID.

## Privacy

- Before any raw output is stored, `ids.redact_smi_xml` replaces `<uuid>` and every `<*serial*>` element with a hash marker. It also removes `<processes>` lists.
- Then `RawStore.scrub` replaces every known UUID and serial anywhere in any raw output.
- The kernel log keeps XID lines only, without `pid=` and `name=`.
- The server parser accepts redacted XML and gets the same card IDs (`tests/test_smi_xml.py`).

## Sources

- The `nvidia-smi -q -x` XML is the main evidence, because the registry can check parsed values against it.
- NVML gives no raw text to check. dud uses NVML to fill values that the XML does not include (for example bank availability on older drivers) and as a cross-check. A disagreement becomes a finding.
- Status rules for N/A: on a known data center model (`gpumodels.py`), N/A for ECC or row remap values means `blocked` (reason `hidden_on_supported_model`). If ECC mode is disabled, the reason is `ecc_disabled`. On A100 and later, retired pages are `not_supported` (reason `replaced_by_row_remap`).

## Decisions from the owner (31 Oct 2026)

- Registry server: TypeScript on Cloudflare Workers.
- API address: `*.workers.dev` for now. The CLI will have a `DUD_API_URL` override so that a move to a custom domain does not break old installs.
- An aggregate counter that is lower than an earlier reading of the same card: flag the submission, keep it, grant no access, and send it to admin review. Root can clear aggregate ECC counts, so a decrease is not always fraud.
- `dud quick` does not send readings to the registry in v1. The schema supports `mode: "quick"` documents if this changes.
- Package name on PyPI: `dud-gpu` (`dud` is taken). The command is `dud`.

## Values to check against real output

These come from the known format, not from a real GPU. Check them when real fixtures arrive.

- Product names in `gpumodels.py`, mainly H200 and H100 NVL.
- XML element names for row remap bank availability (`remapped_row_histogram/row_remap_histogram_*`).
- The number of banks in the fixtures (2560 for H100, 640 for A100). These are placeholders.
- NVML memory total versus nvidia-smi `fb_memory_usage/total`. They must be equal, or the cross-check gives false findings.
