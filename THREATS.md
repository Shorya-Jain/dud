# dud threat model

The dud client is open source. Anyone can change it.
Thus the registry trusts nothing that the client says, and all checks run on the registry server.

Nobody can make fraud impossible.
The goal is:

1. Fraud must cost more than an honest full test.
2. When fraud succeeds, the damage must be small and an admin must be able to find it.

Each section below gives the threat, the defenses and the remaining gap.
The code for each defense is in `server/src/`.
The settings are in `server/wrangler.toml` and `specs.yaml`.

## 1. Fake submissions to get access

**Threat.** A person without a GPU sends a made-up full-test result and gets registry access.

**Defenses.**

- At the start of `dud full`, the registry gives a challenge with a single-use nonce. The nonce expires after 3 hours (`CHALLENGE_TTL_HOURS`).
- The challenge is GPU work: many matrix products in FP16 on tensor cores. The nonce and the card ID set the input values. Thus nobody can do the work before the challenge starts.
- The inputs are -1, 0 and 1, so each result is an exact integer. The server can check a result exactly.
- The client sends a Merkle root of a digest for every product. Then the server picks products at random. The client must send each picked product with a Merkle proof. The server checks each product with a Freivalds test and checks its digest (`challenge.ts`, `chalmath.ts`).
- The server clock measures the time from the challenge to the commit. The time must be inside limits for the claimed GPU model (`specs.yaml`, `challenge`):
  - Faster than the datasheet FP16 rate allows: rejected ("too fast").
  - Slower than `min_efficiency` of that rate: rejected ("too slow").
- The GPUs in the result must be the GPUs in the challenge (card ID and model).
- The registry rejects results from mock mode.

**Remaining gap.**

- Software cannot prove which physical GPU did the work. A person can do the challenge on a real GPU of similar speed, and send readings that they made up for other card IDs.
- A consumer GPU with a similar FP16 rate (for example an RTX 4090 for an A100) can be inside the time limits.
- The time limits are not calibrated yet. `min_efficiency` is a first estimate. Calibrate it with real runs before launch.
- A client that skips a fraction f of the products passes the spot checks with probability (1 - f)^s, where s is `samples_per_gpu` (2). This saves only the fraction f of the time, and the result must still be inside the time limit.
- A future fix is GPU attestation (H100 and later, confidential computing mode). The `attestation` field is in the schema for it.

## 2. Made-up or edited readings

**Threat.** A person changes values in the result, for example to make a bad GPU look good.

**Defenses.**

- The server decodes every raw output and checks its SHA-256 and its size.
- The server reads the raw `nvidia-smi -q -x` XML with its own parser and compares every key value with the parsed values in the result. Any difference: rejected (`parsed_values`).
- If the result says that a value came from NVML, the XML must not have that value.
- Memory size and default power limit must agree with `specs.yaml` for the model. The model key must agree with the product name (`specs`).
- Aggregate counters (ECC errors, row remaps, retired pages) must not be lower than an earlier reading of the same card. A lower value: flagged for admin review, no access. A root user can clear aggregate ECC counts, so a lower value is not always fraud (`counters`).
- Times must agree: start, finish and duration, the challenge time, and the nvidia-smi time (`timing`).
- The load-test series must be physically possible (`load.ts`), with these conditions:
  - Power, temperature and clocks stay in their ranges.
  - Power and temperature change.
  - Temperature does not jump and does not fall under load.
  - Power is at least 40 % of the default limit.

**Remaining gap.**

- The XML is text. A careful forger can edit the XML and the parsed values together. Then only the specs, history, time and physics checks can find the edit.
- A clean history (no errors) for a card that the registry never saw passes all checks.
- A forger can make a load series that looks physical.
- Trust weights (section 7) limit the effect of these readings.

## 3. Replays

**Threat.** A person sends an old result again, or a copy of another person's result.

**Defenses.**

- A challenge belongs to one account and can be used only once. After a submission, its status is `used`.
- The registry keeps the SHA-256 of each important raw output (nvidia-smi XML, DCGM output, load series). A submission with the same raw output as an accepted or flagged submission is rejected (`replay`).

**Remaining gap.**

- A change of one byte (for example the time in the XML) gives a new hash. The copy is then an edited reading (section 2), and it still needs a new challenge (section 1).

## 4. One submission, access without end

**Threat.** A person does one full test and uses the registry for a long time.

**Defenses.**

- Access ends `ACCESS_DAYS` (30) days after the last accepted submission that gave access.
- Each account has a daily lookup quota (`DAILY_LOOKUP_QUOTA`, 100). Each card lookup and each stats request counts. The count goes up before the registry sends data.

**Remaining gap.**

- One account can look up 100 cards each day, which is 3000 cards in 30 days.

## 5. Scraping

**Threat.** A person copies the registry data.

**Defenses.**

- A lookup needs the card ID: the SHA-256 of the GPU UUID. A UUID is a random 128-bit value, so nobody can guess card IDs.
- No endpoint lists cards or exports data. A test checks that list paths return 404.
- Lookups by serial number are not possible. Serial numbers are short and in sequence, so a person could try all of them.
- Stats give percentiles only (p10, p50, p90). Stats need at least `STATS_MIN_CARDS` (20) cards and at least 1 / `CONTRIBUTOR_CAP` (10) contributors.
- The registry stores HMAC(`CARD_ID_PEPPER`, card ID), not the card ID. A copy of the database alone does not show which card is which.
- Clients never touch D1 or R2. R2 is a private bucket.

**Remaining gap.**

- A provider knows the UUIDs of its own GPUs, so it can look up its own fleet. This is intended.
- Percentiles for one provider tell something about that provider's fleet. This is intended.
- If the pepper and a database copy both leak, a person can test known serial numbers against the serial IDs.

## 6. Access farming

**Threat.** One person makes many accounts, or uses one GPU to give access to many accounts.

**Defenses.**

- There is one dud account per GitHub account. The registry keys accounts on the GitHub user ID.
- The registry records the age of the GitHub account. A submission from an account younger than `NEW_GITHUB_ACCOUNT_DAYS` (30) is flagged and gives no access until an admin accepts it.
- A card can give access to only one account in `CARD_UNLOCK_DAYS` (30) days. If any GPU in a submission gave access to another account in that time, the submission gives no access. Its data still goes into the registry.
- A submission gives access only if it includes all GPUs on the node (`ACCESS_REQUIRES_ALL_GPUS`). Thus one 8-GPU node cannot give access to 8 accounts.
- Limits per day: `CHALLENGES_PER_DAY` (10) and `SUBMISSIONS_PER_DAY` (10) per account, and `LOGINS_PER_IP_PER_DAY` (30) per IP address.

**Remaining gap.**

- A person can buy old GitHub accounts.
- A person with many nodes can give access to one account per node every 30 days. Each one costs a real full test.
- An honest renter who gets a node that gave access to another renter in the last 30 days gets no access from that node. This is the cost of this defense.

## 7. Poisoning

**Threat.** A provider makes its own cards look good, or makes a competitor's cards look bad.

**Defenses.**

- New contributors start with low trust (`INITIAL_TRUST`, 0.2). Lookups mark their readings "low trust".
- Trust goes up (+0.05) when a contributor's readings agree with other contributors' readings of the same cards. It goes down (-0.2) when they do not agree, and the registry makes an admin flag (`trust.ts`).
- Stats weight each reading by the trust of its contributor.
- One contributor can have at most `CONTRIBUTOR_CAP` (10 %) of the weight for a model or a model and provider.
- Flagged and rejected submissions are not in lookups or stats.
- An admin can quarantine a contributor. Then lookups and stats do not show that contributor's readings.

**Remaining gap.**

- Many contributors with old GitHub accounts can act together.
- To make a competitor's card look bad, a person needs the UUID of that card and a challenge (section 1). A card with few readings is the easiest target. Low trust and the disagreement check limit the effect.

## 8. Token sharing

**Threat.** A person with access gives the token to other people.

**Defenses.**

- The registry stores only the SHA-256 of each token.
- Each account has one active token. A new `dud login` stops the old token.
- The registry records the networks (Cloudflare ASN and country) that use each account each day.
  - More than `SHARE_FLAG_NETWORKS` (6) networks in one day: admin flag.
  - More than `SHARE_REVOKE_NETWORKS` (12): the registry stops the token automatically.
- The daily quota limits the use of a shared token.
- An admin can stop a token (`dud_admin.py revoke`).

**Remaining gap.**

- Sharing inside one network, or through a few networks or a VPN, is not visible.
- Renters move between providers, so the limits must be loose.

## Other threats

| Threat | Defense | Remaining gap |
|---|---|---|
| A raw UUID or serial number leaves the node | The client replaces them with hashes before it writes or sends anything. The server rejects XML that has a raw UUID. | A new nvidia-smi field with an identifier in an unexpected element. |
| Hostile XML (very deep, very large) | A small parser with no external entities. Limits on depth (32) and element count (200 000). Body limit `MAX_SUBMISSION_MB` (40). | None known. |
| Too much server work | Daily limits. Each reveal checks one product (about 0.5 s of CPU). Worker CPU limit 30 s. | Many IP addresses can call login. Cloudflare protection helps. |
| Admin token theft | The token is a Cloudflare secret. The server compares it in constant time. Every admin action goes into `audit_log`. | One token, no second factor. A future fix is Cloudflare Access in front of `/v1/admin/`. |
| Pepper change or loss | The deploy guide tells you to keep the pepper safe and never change it. | A lost pepper breaks the link between old and new readings. |
| A modified client that skips redaction | The server rejects XML with a raw UUID. | The registry cannot protect a user from a client that the user changed. |
