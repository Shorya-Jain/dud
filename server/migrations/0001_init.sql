-- dud registry, schema 1. Apply with: npx wrangler d1 migrations apply dud-registry --remote
-- Times: *_at columns are ISO 8601 UTC text, *_ms columns are Unix milliseconds.

CREATE TABLE accounts (
  id TEXT PRIMARY KEY,
  github_id INTEGER NOT NULL UNIQUE,
  github_login TEXT NOT NULL,
  github_created_at TEXT,
  created_at TEXT NOT NULL,
  access_until TEXT,                         -- NULL: no access.
  trust REAL NOT NULL DEFAULT 0.2,           -- 0..1. New contributors start low.
  status TEXT NOT NULL DEFAULT 'active'      -- active | quarantined
);

-- Only SHA-256 hashes of tokens. One active token per account.
CREATE TABLE tokens (
  token_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  created_at TEXT NOT NULL,
  revoked_at TEXT,
  revoked_reason TEXT
);
CREATE INDEX tokens_account ON tokens(account_id);

CREATE TABLE challenges (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  nonce TEXT NOT NULL UNIQUE,
  created_ms INTEGER NOT NULL,
  expires_ms INTEGER NOT NULL,
  rounds_json TEXT NOT NULL,                 -- Per GPU: card ID, model, seed, params, count, time bounds.
  status TEXT NOT NULL,                      -- issued | committed | verified | failed | used
  committed_ms INTEGER,
  elapsed_ms INTEGER,
  roots_json TEXT,                           -- Merkle root per GPU.
  samples_json TEXT,                         -- Products that the server picked, and their state.
  fail_reason TEXT,
  used_by TEXT                               -- Submission ID.
);
CREATE INDEX challenges_account ON challenges(account_id, created_ms);

CREATE TABLE submissions (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  challenge_id TEXT,
  received_at TEXT NOT NULL,
  status TEXT NOT NULL,                      -- accepted | flagged | rejected
  grants_access INTEGER NOT NULL DEFAULT 0,
  access_eligible INTEGER NOT NULL DEFAULT 0, -- Would give access if accepted (for admin review).
  decision_reason TEXT NOT NULL,
  provider TEXT,
  dud_version TEXT,
  run_started_at TEXT,
  gpu_count INTEGER,
  r2_key TEXT,
  reviewed_at TEXT,
  review_note TEXT
);
CREATE INDEX submissions_account ON submissions(account_id, received_at);
CREATE INDEX submissions_status ON submissions(status);

-- Why each submission was accepted, flagged or rejected.
CREATE TABLE submission_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id TEXT NOT NULL,
  check_name TEXT NOT NULL,
  result TEXT NOT NULL,                      -- pass | flag | reject
  detail TEXT
);
CREATE INDEX submission_checks_submission ON submission_checks(submission_id);

-- card_id = HMAC(CARD_ID_PEPPER, client card ID). The client card ID never is stored.
CREATE TABLE cards (
  card_id TEXT PRIMARY KEY,
  serial_key TEXT,
  model_key TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE INDEX cards_serial ON cards(serial_key);

CREATE TABLE readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id TEXT NOT NULL,
  card_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  status TEXT NOT NULL,                      -- Copy of the submission status.
  observed_at TEXT NOT NULL,
  model_key TEXT,
  provider TEXT,
  driver_version TEXT,
  vbios TEXT,
  memory_total_mib INTEGER,
  ecc_vol_corr INTEGER, ecc_vol_unc INTEGER,
  ecc_agg_corr INTEGER, ecc_agg_unc INTEGER,
  remap_corr INTEGER, remap_unc INTEGER, remap_pending INTEGER, remap_failed INTEGER,
  bank_max INTEGER, bank_high INTEGER, bank_partial INTEGER, bank_low INTEGER, bank_none INTEGER,
  retired_corr INTEGER, retired_unc INTEGER,
  xid_count INTEGER,
  blocked_count INTEGER,
  verdict TEXT,
  perf_json TEXT,
  gpu_json TEXT NOT NULL                     -- The GPU entry of the result document (no raw output).
);
CREATE INDEX readings_card ON readings(card_id, observed_at);
CREATE INDEX readings_model ON readings(model_key);

CREATE TABLE raw_hashes (
  sha256 TEXT PRIMARY KEY,
  submission_id TEXT NOT NULL,
  raw_id TEXT NOT NULL
);

CREATE TABLE card_unlocks (
  card_id TEXT NOT NULL,
  account_id TEXT NOT NULL,
  submission_id TEXT NOT NULL,
  unlocked_at TEXT NOT NULL,
  PRIMARY KEY (card_id, submission_id)
);
CREATE INDEX card_unlocks_card ON card_unlocks(card_id, unlocked_at);

-- Counters per day: lookups, challenges, submissions, logins (by IP).
CREATE TABLE daily_usage (
  subject TEXT NOT NULL,                     -- Account ID or "ip:<address>".
  day TEXT NOT NULL,                         -- YYYY-MM-DD (UTC).
  kind TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (subject, day, kind)
);

-- Networks (Cloudflare ASN and country) that used each account each day. For token-sharing detection.
CREATE TABLE request_networks (
  account_id TEXT NOT NULL,
  day TEXT NOT NULL,
  network TEXT NOT NULL,
  PRIMARY KEY (account_id, day, network)
);

CREATE TABLE admin_flags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  account_id TEXT,
  submission_id TEXT,
  detail TEXT,
  resolved_at TEXT,
  resolution TEXT
);
CREATE INDEX admin_flags_open ON admin_flags(resolved_at);

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  detail TEXT
);
