-- Transparency log (docs/DESIGN.md, "Transparency log"). Append-only.
-- Each entry is a change to what lookups show: a reading that became visible,
-- or an account that was quarantined or made active again.

-- Entries that wait for the next cron run. The cron run gives them a sequence number.
CREATE TABLE log_pending (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  entry_json TEXT NOT NULL,
  submission_id TEXT,                        -- For reading entries: the reading to update with log_seq.
  card_id TEXT
);

-- leaf = SHA-256("dud-log-v1:leaf:" + entry_json)
-- chain = SHA-256("dud-log-v1:chain:" + previous chain + leaf). The chain before entry 1 is 64 zeros.
CREATE TABLE log (
  seq INTEGER PRIMARY KEY,
  added_at TEXT NOT NULL,
  entry_json TEXT NOT NULL,
  leaf TEXT NOT NULL,
  chain TEXT NOT NULL
);

-- The chain value at the first cron run of each UTC day. The registry publishes these.
CREATE TABLE log_heads (
  day TEXT PRIMARY KEY,
  seq INTEGER NOT NULL,
  chain TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- The fingerprint of each reading, made when the registry accepted the submission.
ALTER TABLE readings ADD COLUMN log_fp TEXT;
ALTER TABLE readings ADD COLUMN log_canonical TEXT;
ALTER TABLE readings ADD COLUMN log_seq INTEGER;
