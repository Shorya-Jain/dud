// Transparency log (docs/DESIGN.md, "Transparency log").
//
// An append-only list of changes to what lookups show. Each entry is chained to
// the one before it with SHA-256, so a change to an old entry changes every
// chain value after it. The registry publishes the chain value of each day
// (GET /v1/log/heads). The chain values contain no registry data.
// Accounts with access can download the entries and check the chain (dud log).

import { bump, requireAccess, type Ctx } from "./auth.ts";
import { sha256Hex } from "./crypto.ts";
import { iso } from "./env.ts";
import { ApiError, json } from "./http.ts";

export const ZERO = "0".repeat(64);
const PAGE_MAX = 1000;

// JSON with sorted keys and no spaces. The client and the server must give the same text.
export function canonical(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v ?? null);
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`).join(",")}}`;
}

// One reading as a lookup shows it, without the parts that change after the test (trust, yours, log).
export function publicReading(r: Record<string, any>) {
  return {
    date: String(r.observed_at).slice(0, 10),
    model_key: r.model_key,
    provider: r.provider ?? null,
    driver_version: r.driver_version,
    vbios: r.vbios,
    memory_total_mib: r.memory_total_mib,
    ecc: { volatile_correctable: r.ecc_vol_corr, volatile_uncorrectable: r.ecc_vol_unc,
           aggregate_correctable: r.ecc_agg_corr, aggregate_uncorrectable: r.ecc_agg_unc },
    row_remap: { correctable: r.remap_corr, uncorrectable: r.remap_unc, pending: r.remap_pending === null ? null : !!r.remap_pending,
                 failed: r.remap_failed === null ? null : !!r.remap_failed,
                 bank_availability: { max: r.bank_max, high: r.bank_high, partial: r.bank_partial, low: r.bank_low, none: r.bank_none } },
    retired_pages: { correctable: r.retired_corr, uncorrectable: r.retired_unc },
    xid_count: r.xid_count,
    blocked_values: r.blocked_count,
    verdict: r.verdict,
    verdict_reasons: r.verdict_json ? JSON.parse(r.verdict_json).map((x: any) => x.text) : [],
    perf: r.perf_json ? JSON.parse(r.perf_json) : null,
  };
}

// The fingerprint binds the reading to the client card ID, which the registry does not store.
export async function fingerprint(clientCardId: string, canonicalText: string): Promise<string> {
  return sha256Hex(`dud-log-v1:reading:${clientCardId}:${canonicalText}`);
}

export async function leafOf(entryJson: string): Promise<string> {
  return sha256Hex(`dud-log-v1:leaf:${entryJson}`);
}

export async function chainOf(prev: string, leaf: string): Promise<string> {
  return sha256Hex(`dud-log-v1:chain:${prev}${leaf}`);
}

export function readingEntry(fp: string): string {
  return JSON.stringify({ v: 1, type: "reading", fp });
}

export async function accountEntry(accountId: string, status: string): Promise<string> {
  return JSON.stringify({ v: 1, type: "account", account: await sha256Hex(`dud-log-v1:account:${accountId}`), status });
}

export function pendingStmt(ctx: Ctx, entryJson: string, submissionId: string | null = null, cardId: string | null = null) {
  return ctx.env.DB.prepare("INSERT INTO log_pending (created_at, entry_json, submission_id, card_id) VALUES (?, ?, ?, ?)")
    .bind(iso(ctx.now()), entryJson, submissionId, cardId);
}

// Give the waiting entries their sequence numbers and chain values. The cron run and the admin call this.
export async function appendPending(ctx: Ctx, limit = 200): Promise<number> {
  const db = ctx.env.DB;
  const pending = (await db.prepare("SELECT * FROM log_pending ORDER BY id LIMIT ?").bind(limit).all<Record<string, any>>()).results;
  if (!pending.length) return 0;
  const last = await db.prepare("SELECT seq, chain FROM log ORDER BY seq DESC LIMIT 1").first<{ seq: number; chain: string }>();
  let seq = last?.seq ?? 0;
  let chain = last?.chain ?? ZERO;
  const now = iso(ctx.now());
  const stmts = [];
  for (const p of pending) {
    seq += 1;
    const leaf = await leafOf(p.entry_json);
    chain = await chainOf(chain, leaf);
    stmts.push(db.prepare("INSERT INTO log (seq, added_at, entry_json, leaf, chain) VALUES (?, ?, ?, ?, ?)").bind(seq, now, p.entry_json, leaf, chain));
    if (p.submission_id && p.card_id)
      stmts.push(db.prepare("UPDATE readings SET log_seq = ? WHERE submission_id = ? AND card_id = ?").bind(seq, p.submission_id, p.card_id));
    stmts.push(db.prepare("DELETE FROM log_pending WHERE id = ?").bind(p.id));
  }
  // One batch: all entries or none. A second run at the same time fails on the seq key and changes nothing.
  await db.batch(stmts);
  return pending.length;
}

// The head of the day: the chain value at the first run after 00:00 UTC.
export async function recordHead(ctx: Ctx): Promise<void> {
  const last = await ctx.env.DB.prepare("SELECT seq, chain FROM log ORDER BY seq DESC LIMIT 1").first<{ seq: number; chain: string }>();
  await ctx.env.DB.prepare("INSERT OR IGNORE INTO log_heads (day, seq, chain, created_at) VALUES (?, ?, ?, ?)")
    .bind(iso(ctx.now()).slice(0, 10), last?.seq ?? 0, last?.chain ?? ZERO, iso(ctx.now())).run();
}

export async function runLog(ctx: Ctx): Promise<void> {
  while ((await appendPending(ctx)) > 0);
  await recordHead(ctx);
}

// Public: the daily chain values only. No sequence numbers, so they do not show how many readings there are.
export async function publicHeads(ctx: Ctx): Promise<Response> {
  const rows = (await ctx.env.DB.prepare("SELECT day, chain FROM log_heads ORDER BY day").all<{ day: string; chain: string }>()).results;
  return json({ heads: rows });
}

// Access only: the entries, one page at a time, and the heads with their sequence numbers.
export async function logPage(ctx: Ctx, params: URLSearchParams): Promise<Response> {
  const a = await requireAccess(ctx);
  await bump(ctx, a.id, "log_page", ctx.cfg.LOG_PAGES_PER_DAY, "rate_limited");
  const after = Number(params.get("after") ?? 0);
  const limit = Math.min(PAGE_MAX, Number(params.get("limit") ?? PAGE_MAX));
  if (!Number.isInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1)
    throw new ApiError(400, "bad_request", { detail: "after and limit must be whole numbers." });
  const db = ctx.env.DB;
  const entries = (await db.prepare("SELECT seq, added_at, entry_json AS entry, leaf, chain FROM log WHERE seq > ? ORDER BY seq LIMIT ?")
    .bind(after, limit).all()).results;
  const heads = (await db.prepare("SELECT day, seq, chain FROM log_heads ORDER BY day").all()).results;
  const last = await db.prepare("SELECT MAX(seq) AS seq FROM log").first<{ seq: number | null }>();
  return json({ entries, heads, last_seq: last?.seq ?? 0 });
}

export function lookupLog(r: Record<string, any>) {
  return r.log_fp ? { seq: r.log_seq ?? null, fp: r.log_fp, canonical: r.log_canonical } : null;
}
