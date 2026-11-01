// POST /v1/submissions: every server-side check on a full-test result.
// Each check is logged with pass, flag or reject. See THREATS.md for the reasons.

import { addFlag, authenticate, bump, type Account, type Ctx } from "./auth.ts";
import type { ChallengeRow, Round } from "./challenge.ts";
import { b64decode, gunzip, gzip, hmacHex, randomHex, sha256Hex } from "./crypto.ts";
import { iso } from "./env.ts";
import { ApiError, json, readJson } from "./http.ts";
import { gradeGpu } from "./grade.ts";
import { checkLoad } from "./load.ts";
import { identify } from "./models.ts";
import { validate } from "./schema.ts";
import { parseSmi, smiTimestampMs, type SmiDoc } from "./smi.ts";
import specs from "./specs.json" with { type: "json" };
import { compare, nextTrust, type ReadingLite } from "./trust.ts";
import schema from "../../src/dud/schema/result.v1.json" with { type: "json" };

type Result = "pass" | "flag" | "reject";
type Check = { name: string; result: Result; detail: string | null };

// Raw outputs that must never repeat between submissions. Each one contains a time.
// DCGM output is not here: two honest runs on the same node can give the same text.
const REPLAY_IDS = /^(smi_q_x|load.*|perf.*)$/;
const COUNTERS = ["ecc_agg_corr", "ecc_agg_unc", "remap_corr", "remap_unc", "retired_corr", "retired_unc"] as const;
const MINUTE = 60_000;

class Checks {
  list: Check[] = [];
  pass(name: string, detail: string | null = null) { this.list.push({ name, result: "pass", detail }); }
  flag(name: string, detail: string) { this.list.push({ name, result: "flag", detail }); }
  reject(name: string, detail: string) { this.list.push({ name, result: "reject", detail }); }
  get rejected() { return this.list.some((c) => c.result === "reject"); }
  status(): "accepted" | "flagged" | "rejected" {
    if (this.rejected) return "rejected";
    return this.list.some((c) => c.result === "flag") ? "flagged" : "accepted";
  }
}

class Stop extends Error {}

function getPath(obj: any, path: string): any {
  return path.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

function val(gpu: any, path: string): any {
  const f = getPath(gpu, path);
  return f && f.status === "ok" ? f.value : null;
}

function asInt(v: any): number | null {
  return typeof v === "boolean" ? (v ? 1 : 0) : typeof v === "number" ? v : null;
}

export async function cardKey(ctx: Ctx, kind: "card" | "serial", clientHash: string): Promise<string> {
  return hmacHex(ctx.env.CARD_ID_PEPPER, `${kind}:${clientHash}`);
}

// The registry's verdict. It ignores the verdict that the client sends.
function serverVerdict(doc: any, gpu: any) {
  const v = gradeGpu(gpu, doc.run.mode === "quick" ? "quick" : "full");
  return {
    verdict: v.verdict,
    verdict_json: JSON.stringify(v.results.filter((r) => r.result === "fail" || r.result === "missing")),
  };
}

// Values with status "blocked" in one GPU entry. The load series has no fields, so the walk skips it.
function countBlocked(o: any): number {
  if (!o || typeof o !== "object") return 0;
  if (Array.isArray(o)) return o.reduce((n, x) => n + countBlocked(x), 0);
  let n = o.status === "blocked" ? 1 : 0;
  for (const k in o) if (k !== "load") n += countBlocked(o[k]);
  return n;
}

function readingFrom(doc: any, gpu: any) {
  const blocked = countBlocked(gpu);
  const xid = val(gpu, "history.xid_events");
  return {
    model_key: val(gpu, "identity.model_key"),
    driver_version: val(doc.host, "driver_version"),
    vbios: val(gpu, "identity.vbios"),
    memory_total_mib: val(gpu, "identity.memory_total_mib"),
    ecc_vol_corr: val(gpu, "history.ecc.volatile.correctable"),
    ecc_vol_unc: val(gpu, "history.ecc.volatile.uncorrectable"),
    ecc_agg_corr: val(gpu, "history.ecc.aggregate.correctable"),
    ecc_agg_unc: val(gpu, "history.ecc.aggregate.uncorrectable"),
    remap_corr: val(gpu, "history.row_remap.correctable"),
    remap_unc: val(gpu, "history.row_remap.uncorrectable"),
    remap_pending: asInt(val(gpu, "history.row_remap.pending")),
    remap_failed: asInt(val(gpu, "history.row_remap.failed")),
    bank_max: val(gpu, "history.row_remap.bank_availability.max"),
    bank_high: val(gpu, "history.row_remap.bank_availability.high"),
    bank_partial: val(gpu, "history.row_remap.bank_availability.partial"),
    bank_low: val(gpu, "history.row_remap.bank_availability.low"),
    bank_none: val(gpu, "history.row_remap.bank_availability.none"),
    retired_corr: val(gpu, "history.retired_pages.correctable"),
    retired_unc: val(gpu, "history.retired_pages.uncorrectable"),
    xid_count: Array.isArray(xid) ? xid.length : null,
    blocked_count: blocked,
    perf_json: gpu.perf ? JSON.stringify(gpu.perf) : null,
    ...serverVerdict(doc, gpu),
  };
}

// --- The checks ---------------------------------------------------------------------

async function checkChallenge(ctx: Ctx, c: Checks, doc: any, account: Account): Promise<{ row: ChallengeRow; rounds: Round[] }> {
  const id = doc.challenge?.challenge_id;
  if (typeof id !== "string") {
    c.reject("challenge", "the result has no challenge ID");
    throw new Stop();
  }
  const row = await ctx.env.DB.prepare("SELECT * FROM challenges WHERE id = ?").bind(id).first<ChallengeRow>();
  if (!row || row.account_id !== account.id) {
    c.reject("challenge", "the challenge does not exist or belongs to another account");
    throw new Stop();
  }
  if (row.status === "used") c.reject("challenge", "the challenge was used before (replay)");
  else if (row.status !== "verified") c.reject("challenge", `the challenge is not verified (status ${row.status}${row.fail_reason ? `: ${row.fail_reason}` : ""})`);
  else if (row.expires_ms < ctx.now()) c.reject("challenge", "the challenge expired");
  else if (doc.challenge.nonce !== row.nonce) c.reject("challenge", "the nonce does not match");
  else c.pass("challenge", `elapsed ${row.elapsed_ms} ms`);
  return { row, rounds: JSON.parse(row.rounds_json) };
}

function checkCards(c: Checks, doc: any, rounds: Round[]) {
  const docIds = doc.gpus.map((g: any) => val(g, "card.uuid_sha256"));
  if (docIds.some((x: any) => !x)) return c.reject("card_ids", "a GPU has no card ID");
  const want = new Set(rounds.map((r) => r.card_id));
  if (docIds.length !== want.size || docIds.some((x: string) => !want.has(x)))
    return c.reject("card_ids", "the GPUs in the result are not the GPUs in the challenge");
  for (const r of rounds) {
    const g = doc.gpus.find((x: any) => val(x, "card.uuid_sha256") === r.card_id);
    if (val(g, "identity.model_key") !== r.model_key) return c.reject("card_ids", "the model in the result is not the model in the challenge");
  }
  c.pass("card_ids");
}

async function checkRaw(ctx: Ctx, c: Checks, doc: any): Promise<Record<string, string>> {
  const texts: Record<string, string> = {};
  for (const e of doc.raw) {
    try {
      const bytes = await gunzip(b64decode(e.content));
      if (bytes.length !== e.bytes || (await sha256Hex(bytes)) !== e.sha256) {
        c.reject("raw_hashes", `raw output ${e.id}: the hash or size does not match the content`);
        return texts;
      }
      texts[e.id] = new TextDecoder().decode(bytes);
    } catch {
      c.reject("raw_hashes", `raw output ${e.id}: dud cannot decode it`);
      return texts;
    }
  }
  if (!texts.smi_q_x) return (c.reject("raw_hashes", "the nvidia-smi XML is missing"), texts);
  c.pass("raw_hashes", `${doc.raw.length} raw outputs`);

  for (const e of doc.raw) {
    if (!REPLAY_IDS.test(e.id) || e.bytes === 0) continue;
    const seen = await ctx.env.DB.prepare("SELECT submission_id FROM raw_hashes WHERE sha256 = ?").bind(e.sha256).first<{ submission_id: string }>();
    if (seen) {
      c.reject("replay", `raw output ${e.id} is the same as in submission ${seen.submission_id}`);
      return texts;
    }
  }
  c.pass("replay");
  return texts;
}

function same(a: any, b: any): boolean {
  return typeof a === "number" && typeof b === "number" ? Math.abs(a - b) < 1e-9 : a === b;
}

function checkParsed(c: Checks, doc: any, smi: SmiDoc) {
  const problems: string[] = [];
  if (smi.gpus.some((g) => g.raw_uuid_present)) problems.push("the XML contains a raw UUID");
  for (const [key, path] of [["driver_version", "driver_version"], ["timestamp", "smi_timestamp"], ["attached_gpus", "attached_gpus"]]) {
    const s = smi.top[key];
    const d = doc.host[path];
    if (s.ok !== (d.status === "ok") || (s.ok && !same(s.value, d.value))) problems.push(`host.${path}`);
  }
  for (const gpu of doc.gpus) {
    const id = val(gpu, "card.uuid_sha256");
    const sg = smi.gpus.find((g) => g.uuid_sha256 === id);
    if (!sg) {
      problems.push(`GPU ${gpu.index}: card ID not in the XML`);
      continue;
    }
    if (sg.serial_sha256 !== val(gpu, "card.serial_sha256")) problems.push(`GPU ${gpu.index}: serial ID`);
    for (const [path, s] of Object.entries(sg.values)) {
      const f = getPath(gpu, path);
      if (!f) continue;
      if (f.source === "nvml") {
        if (s.ok) problems.push(`GPU ${gpu.index}: ${path} says NVML, but the XML has the value`);
      } else if (s.ok !== (f.status === "ok") || (s.ok && !same(s.value, f.value))) {
        problems.push(`GPU ${gpu.index}: ${path}`);
      }
    }
  }
  const tested = doc.gpus.length;
  if (doc.run.options.gpus === null && tested !== smi.gpus.length) problems.push("the result does not have all GPUs in the XML");
  if (problems.length) c.reject("parsed_values", `values do not match the raw XML: ${problems.slice(0, 6).join("; ")}`);
  else c.pass("parsed_values");
}

function checkSpecs(c: Checks, doc: any) {
  const problems: string[] = [];
  for (const gpu of doc.gpus) {
    const key = val(gpu, "identity.model_key");
    if (identify(val(gpu, "identity.name")) !== key) {
      problems.push(`GPU ${gpu.index}: the model key does not match the product name`);
      continue;
    }
    const spec = (specs.models as Record<string, any>)[key];
    if (!spec) {
      problems.push(`GPU ${gpu.index}: no datasheet values for ${key}`);
      continue;
    }
    const mem = val(gpu, "identity.memory_total_mib");
    if (mem === null || mem < spec.memory_mib.min || mem > spec.memory_mib.max)
      problems.push(`GPU ${gpu.index}: memory ${mem} MiB is not correct for ${key}`);
    const pw = val(gpu, "identity.power_limit_default_w");
    if (pw === null || pw < spec.power_default_w.min || pw > spec.power_default_w.max)
      problems.push(`GPU ${gpu.index}: default power limit ${pw} W is not correct for ${key}`);
  }
  if (problems.length) c.reject("specs", problems.join("; "));
  else c.pass("specs");
}

function checkTiming(ctx: Ctx, c: Checks, doc: any, row: ChallengeRow, smiTimestamp: string | null) {
  const start = Date.parse(doc.run.started_at);
  const end = Date.parse(doc.run.finished_at);
  const dur = doc.run.duration_s * 1000;
  const problems: string[] = [];
  if (!(end >= start)) problems.push("the finish time is before the start time");
  if (Math.abs(end - start - dur) > Math.max(MINUTE, 0.05 * dur)) problems.push("the duration does not match the start and finish times");
  if (end > ctx.now() + 5 * MINUTE) problems.push("the finish time is in the future");
  if (row.created_ms < start - 10 * MINUTE || row.created_ms > end) problems.push("the challenge is not inside the test time");
  if (row.committed_ms !== null && row.committed_ms > end + 5 * MINUTE) problems.push("the challenge commit is after the test");
  const loadMin = doc.run.options.load_minutes;
  const devMock = doc.run.mock && ctx.cfg.ALLOW_MOCK;
  if (!devMock && doc.gpus.some((g: any) => g.load) && loadMin && dur < loadMin * MINUTE) problems.push("the test is shorter than the load time");
  if (problems.length) return c.reject("timing", problems.join("; "));

  if (smiTimestamp === null || doc.run.utc_offset_s === null) return c.flag("timing", "dud cannot check the nvidia-smi time");
  const smiMs = smiTimestampMs(smiTimestamp, doc.run.utc_offset_s);
  if (smiMs === null) return c.flag("timing", "the nvidia-smi time has an unknown format");
  if (smiMs < start - 15 * MINUTE || smiMs > end + 15 * MINUTE) return c.reject("timing", "the nvidia-smi time is not inside the test time");
  c.pass("timing");
}

function checkLoads(ctx: Ctx, c: Checks, doc: any) {
  const missing = doc.gpus.filter((g: any) => !g.load);
  if (missing.length) {
    if (ctx.cfg.REQUIRE_LOAD) return c.reject("load", `${missing.length} GPUs have no load test`);
    return c.pass("load", "no load test (REQUIRE_LOAD is off)");
  }
  const problems: string[] = [];
  for (const g of doc.gpus) {
    const p = checkLoad(g.load, {
      default_w: val(g, "identity.power_limit_default_w"),
      max_w: val(g, "identity.power_limit_max_w"),
      max_sm_mhz: val(g, "identity.max_clocks.sm_mhz"),
    });
    if (p.length) problems.push(`GPU ${g.index}: ${p.slice(0, 3).join(", ")}`);
  }
  if (problems.length) c.reject("load", problems.join("; "));
  else c.pass("load");
}

async function checkHistory(ctx: Ctx, c: Checks, doc: any, keys: string[]) {
  const problems: string[] = [];
  for (let i = 0; i < doc.gpus.length; i++) {
    const prev = await ctx.env.DB.prepare(
      "SELECT * FROM readings WHERE card_id = ? AND status IN ('accepted', 'flagged') AND observed_at <= ? ORDER BY observed_at DESC LIMIT 1",
    ).bind(keys[i], doc.run.started_at).first<Record<string, any>>();
    if (!prev) continue;
    const cur = readingFrom(doc, doc.gpus[i]);
    for (const k of COUNTERS) {
      const a = (cur as any)[k];
      const b = prev[k];
      if (a !== null && b !== null && a < b) problems.push(`GPU ${doc.gpus[i].index}: ${k} is ${a}, an earlier reading has ${b}`);
    }
  }
  if (problems.length) c.flag("counters", `aggregate counters are lower than earlier readings: ${problems.join("; ")}`);
  else c.pass("counters");
}

function checkAccount(ctx: Ctx, c: Checks, account: Account) {
  if (account.status !== "active") c.flag("account", `the account is ${account.status}`);
  const age = account.github_created_at ? (ctx.now() - Date.parse(account.github_created_at)) / 86_400_000 : 0;
  if (age < ctx.cfg.NEW_GITHUB_ACCOUNT_DAYS) c.flag("account", `the GitHub account is ${Math.floor(age)} days old`);
  if (!c.list.some((x) => x.name === "account")) c.pass("account");
}

async function accessEligibility(ctx: Ctx, doc: any, smi: SmiDoc | null, keys: string[], accountId: string): Promise<{ ok: boolean; why: string }> {
  if (ctx.cfg.ACCESS_REQUIRES_ALL_GPUS && smi && doc.gpus.length < smi.gpus.length)
    return { ok: false, why: "the test did not include all GPUs on the node" };
  const since = iso(ctx.now() - ctx.cfg.CARD_UNLOCK_DAYS * 86_400_000);
  for (const key of keys) {
    const other = await ctx.env.DB.prepare(
      "SELECT 1 FROM card_unlocks WHERE card_id = ? AND account_id != ? AND unlocked_at >= ? LIMIT 1",
    ).bind(key, accountId, since).first();
    if (other) return { ok: false, why: `a GPU on this node gave access to another account in the last ${ctx.cfg.CARD_UNLOCK_DAYS} days` };
  }
  return { ok: true, why: "" };
}

// --- The handler ----------------------------------------------------------------------

export async function submit(ctx: Ctx): Promise<Response> {
  const account = await authenticate(ctx);
  await bump(ctx, account.id, "submission", ctx.cfg.SUBMISSIONS_PER_DAY, "rate_limited");
  const doc = await readJson(ctx.request, ctx.cfg.MAX_SUBMISSION_MB * 1_000_000);
  const c = new Checks();
  let challenge: { row: ChallengeRow; rounds: Round[] } | null = null;
  let smi: SmiDoc | null = null;
  const keys: string[] = [];

  try {
    const errors = validate(schema, doc);
    if (errors.length) {
      c.reject("schema", errors.slice(0, 5).join("; "));
      throw new Stop();
    }
    c.pass("schema");
    if (doc.run.mode !== "full") c.reject("mode", "only full tests go to the registry");
    else if (doc.run.mock && !ctx.cfg.ALLOW_MOCK) c.reject("mode", "the result comes from mock mode");
    else c.pass("mode");
    if (doc.gpus.length === 0) {
      c.reject("gpus", "the result has no GPUs");
      throw new Stop();
    }

    challenge = await checkChallenge(ctx, c, doc, account);
    checkCards(c, doc, challenge.rounds);
    for (const g of doc.gpus) keys.push(await cardKey(ctx, "card", val(g, "card.uuid_sha256") ?? "none"));
    const texts = await checkRaw(ctx, c, doc);
    if (c.rejected) throw new Stop();
    try {
      smi = parseSmi(texts.smi_q_x);
    } catch (e) {
      c.reject("parsed_values", `dud cannot read the nvidia-smi XML: ${(e as Error).message}`);
      throw new Stop();
    }
    checkParsed(c, doc, smi);
    checkSpecs(c, doc);
    checkTiming(ctx, c, doc, challenge.row, smi.top.timestamp.ok ? smi.top.timestamp.value : null);
    checkLoads(ctx, c, doc);
    if (!c.rejected) await checkHistory(ctx, c, doc, keys);
    if (!c.rejected) {
      const mine = doc.gpus.map((g: any) => `GPU ${g.index} ${serverVerdict(doc, g).verdict}`).join(", ");
      const theirs = doc.gpus.map((g: any) => g.verdict?.verdict ?? "none").join(", ");
      c.pass("verdict", `registry: ${mine}; client: ${theirs}`);
    }
    checkAccount(ctx, c, account);
  } catch (e) {
    if (!(e instanceof Stop)) throw e;
  }

  const status = c.status();
  const eligible = status === "rejected" ? { ok: false, why: "" } : await accessEligibility(ctx, doc, smi, keys, account.id);
  const grants = status === "accepted" && eligible.ok;
  if (status === "accepted") c.pass("access", grants ? "gives access" : `no access: ${eligible.why}`);
  const reason = status === "rejected" ? c.list.filter((x) => x.result === "reject").map((x) => x.name).join(", ")
    : status === "flagged" ? c.list.filter((x) => x.result === "flag").map((x) => x.name).join(", ")
    : grants ? "all checks passed" : eligible.why;

  // --- Store ---
  const db = ctx.env.DB;
  const id = "sub_" + randomHex(12);
  const now = iso(ctx.now());
  const r2Key = ctx.env.RAW ? `submissions/${id}.json.gz` : null;
  if (ctx.env.RAW && r2Key) await ctx.env.RAW.put(r2Key, await gzip(new TextEncoder().encode(JSON.stringify(doc))));
  const stmts = [
    db.prepare(
      "INSERT INTO submissions (id, account_id, challenge_id, received_at, status, grants_access, access_eligible, decision_reason, " +
        "provider, dud_version, run_started_at, gpu_count, r2_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(id, account.id, challenge?.row.id ?? null, now, status, grants ? 1 : 0, eligible.ok ? 1 : 0, reason,
      doc?.run?.provider?.reported ?? null, doc?.run?.dud_version ?? null, doc?.run?.started_at ?? null,
      Array.isArray(doc?.gpus) ? doc.gpus.length : null, r2Key),
    ...c.list.map((x) => db.prepare("INSERT INTO submission_checks (submission_id, check_name, result, detail) VALUES (?, ?, ?, ?)")
      .bind(id, x.name, x.result, x.detail)),
  ];
  if (challenge && challenge.row.status === "verified")
    stmts.push(db.prepare("UPDATE challenges SET status = 'used', used_by = ? WHERE id = ?").bind(id, challenge.row.id));

  if (status !== "rejected") {
    for (const e of doc.raw) if (REPLAY_IDS.test(e.id) && e.bytes > 0)
      stmts.push(db.prepare("INSERT OR IGNORE INTO raw_hashes (sha256, submission_id, raw_id) VALUES (?, ?, ?)").bind(e.sha256, id, e.id));
    for (let i = 0; i < doc.gpus.length; i++) {
      const g = doc.gpus[i];
      const r = readingFrom(doc, g);
      const serial = val(g, "card.serial_sha256");
      stmts.push(db.prepare(
        "INSERT INTO cards (card_id, serial_key, model_key, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) " +
          "ON CONFLICT (card_id) DO UPDATE SET last_seen = excluded.last_seen, serial_key = COALESCE(cards.serial_key, excluded.serial_key)",
      ).bind(keys[i], serial ? await cardKey(ctx, "serial", serial) : null, r.model_key, doc.run.started_at, doc.run.started_at));
      stmts.push(db.prepare(
        "INSERT INTO readings (submission_id, card_id, account_id, status, observed_at, model_key, provider, driver_version, vbios, " +
          "memory_total_mib, ecc_vol_corr, ecc_vol_unc, ecc_agg_corr, ecc_agg_unc, remap_corr, remap_unc, remap_pending, remap_failed, " +
          "bank_max, bank_high, bank_partial, bank_low, bank_none, retired_corr, retired_unc, xid_count, blocked_count, verdict, verdict_json, perf_json, gpu_json) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
      ).bind(id, keys[i], account.id, status, doc.run.started_at, r.model_key, doc.run.provider.reported, r.driver_version, r.vbios,
        r.memory_total_mib, r.ecc_vol_corr, r.ecc_vol_unc, r.ecc_agg_corr, r.ecc_agg_unc, r.remap_corr, r.remap_unc, r.remap_pending,
        r.remap_failed, r.bank_max, r.bank_high, r.bank_partial, r.bank_low, r.bank_none, r.retired_corr, r.retired_unc, r.xid_count,
        r.blocked_count, r.verdict, r.verdict_json, r.perf_json, JSON.stringify(g)));
    }
  }
  if (grants) stmts.push(...grantAccess(ctx, account.id, id, keys));
  await db.batch(stmts);
  if (status === "flagged") await addFlag(ctx, "submission_flagged", account.id, id, reason);
  if (status === "accepted") await updateTrust(ctx, account, doc, keys);

  const updated = await db.prepare("SELECT access_until FROM accounts WHERE id = ?").bind(account.id).first<{ access_until: string | null }>();
  return json({
    submission_id: id,
    status,
    grants_access: grants,
    access_until: updated?.access_until ?? null,
    reason,
    checks: c.list.filter((x) => x.result !== "pass" || x.name === "access"),
  }, status === "rejected" ? 422 : 200);
}

export function grantAccess(ctx: Ctx, accountId: string, submissionId: string, keys: string[]) {
  const db = ctx.env.DB;
  const until = iso(ctx.now() + ctx.cfg.ACCESS_DAYS * 86_400_000);
  const now = iso(ctx.now());
  return [
    db.prepare("UPDATE accounts SET access_until = CASE WHEN access_until IS NULL OR access_until < ? THEN ? ELSE access_until END WHERE id = ?")
      .bind(until, until, accountId),
    ...keys.map((k) => db.prepare("INSERT OR IGNORE INTO card_unlocks (card_id, account_id, submission_id, unlocked_at) VALUES (?, ?, ?, ?)")
      .bind(k, accountId, submissionId, now)),
  ];
}

// Trust goes up when this contributor's readings agree with other contributors' readings of the same cards.
async function updateTrust(ctx: Ctx, account: Account, doc: any, keys: string[]) {
  let trust = account.trust;
  for (let i = 0; i < keys.length; i++) {
    const others = (await ctx.env.DB.prepare(
      "SELECT * FROM readings WHERE card_id = ? AND account_id != ? AND status = 'accepted' ORDER BY observed_at DESC LIMIT 20",
    ).bind(keys[i], account.id).all<ReadingLite>()).results;
    const mine: ReadingLite = { account_id: account.id, observed_at: doc.run.started_at, ...readingFrom(doc, doc.gpus[i]) };
    const cmp = compare(mine, others);
    trust = nextTrust(trust, cmp.result);
    if (cmp.result === "disagree") await addFlag(ctx, "readings_disagree", account.id, null, `GPU ${doc.gpus[i].index}: ${cmp.detail}`);
  }
  if (trust !== account.trust) await ctx.env.DB.prepare("UPDATE accounts SET trust = ? WHERE id = ?").bind(trust, account.id).run();
}
