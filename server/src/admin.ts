// Admin endpoints. They need the ADMIN_TOKEN secret. admin/dud_admin.py calls them.
// Every change goes into audit_log.

import { revokeTokens, type Ctx } from "./auth.ts";
import { gunzip, timingSafeEqual } from "./crypto.ts";
import { iso } from "./env.ts";
import { ApiError, json, readJson } from "./http.ts";
import { grantAccess } from "./submit.ts";

function requireAdmin(ctx: Ctx) {
  const token = ctx.env.ADMIN_TOKEN ?? "";
  const header = ctx.request.headers.get("authorization") ?? "";
  if (token.length < 32 || !timingSafeEqual(header, `Bearer ${token}`)) throw new ApiError(401, "admin_only");
}

async function audit(ctx: Ctx, action: string, target: string, detail: string) {
  await ctx.env.DB.prepare("INSERT INTO audit_log (at, actor, action, target, detail) VALUES (?, 'admin', ?, ?, ?)")
    .bind(iso(ctx.now()), action, target, detail).run();
}

async function accountByIdOrLogin(ctx: Ctx, idOrLogin: string) {
  const a = await ctx.env.DB.prepare("SELECT * FROM accounts WHERE id = ? OR github_login = ?")
    .bind(idOrLogin, idOrLogin).first<Record<string, any>>();
  if (!a) throw new ApiError(404, "not_found");
  return a;
}

export async function admin(ctx: Ctx, parts: string[]): Promise<Response> {
  requireAdmin(ctx);
  const db = ctx.env.DB;
  const method = ctx.request.method;
  const [section, id, action] = parts;

  if (section === "flags" && method === "GET" && !id) {
    const rows = (await db.prepare("SELECT * FROM admin_flags WHERE resolved_at IS NULL ORDER BY id DESC LIMIT 200").all()).results;
    return json({ flags: rows });
  }
  if (section === "flags" && id && action === "resolve" && method === "POST") {
    const body = await readJson(ctx.request, 10_000);
    await db.prepare("UPDATE admin_flags SET resolved_at = ?, resolution = ? WHERE id = ?").bind(iso(ctx.now()), String(body.note ?? ""), Number(id)).run();
    await audit(ctx, "resolve_flag", id, String(body.note ?? ""));
    return json({ ok: true });
  }

  if (section === "submissions" && method === "GET" && !id) {
    const status = new URL(ctx.request.url).searchParams.get("status") ?? "flagged";
    const rows = (await db.prepare(
      "SELECT s.id, s.received_at, s.status, s.decision_reason, s.provider, s.gpu_count, a.github_login " +
        "FROM submissions s JOIN accounts a ON a.id = s.account_id WHERE s.status = ? ORDER BY s.received_at DESC LIMIT 200",
    ).bind(status).all()).results;
    return json({ submissions: rows });
  }
  if (section === "submissions" && id && method === "GET" && !action) {
    const s = await db.prepare("SELECT * FROM submissions WHERE id = ?").bind(id).first<Record<string, any>>();
    if (!s) throw new ApiError(404, "not_found");
    const checks = (await db.prepare("SELECT check_name, result, detail FROM submission_checks WHERE submission_id = ? ORDER BY id").bind(id).all()).results;
    const account = await db.prepare("SELECT id, github_login, github_created_at, trust, status, access_until FROM accounts WHERE id = ?").bind(s.account_id).first();
    return json({ submission: s, checks, account });
  }
  if (section === "submissions" && id && action === "document" && method === "GET") {
    const s = await db.prepare("SELECT r2_key FROM submissions WHERE id = ?").bind(id).first<{ r2_key: string }>();
    const obj = s ? await ctx.env.RAW.get(s.r2_key) : null;
    if (!obj) throw new ApiError(404, "not_found");
    const bytes = await gunzip(new Uint8Array(await obj.arrayBuffer()), 200_000_000);
    return new Response(bytes, { headers: { "content-type": "application/json" } });
  }
  if (section === "submissions" && id && action === "decision" && method === "POST") {
    const body = await readJson(ctx.request, 10_000);
    const decision = body.decision;
    if (decision !== "accept" && decision !== "reject") throw new ApiError(400, "bad_request", { detail: "decision must be accept or reject." });
    const s = await db.prepare("SELECT * FROM submissions WHERE id = ?").bind(id).first<Record<string, any>>();
    if (!s) throw new ApiError(404, "not_found");
    if (s.status !== "flagged") throw new ApiError(409, "bad_request", { detail: `The submission is ${s.status}, not flagged.` });
    const note = String(body.note ?? "");
    const newStatus = decision === "accept" ? "accepted" : "rejected";
    const stmts = [
      db.prepare("UPDATE submissions SET status = ?, reviewed_at = ?, review_note = ? WHERE id = ?").bind(newStatus, iso(ctx.now()), note, id),
      db.prepare("UPDATE readings SET status = ? WHERE submission_id = ?").bind(newStatus, id),
      db.prepare("UPDATE admin_flags SET resolved_at = ?, resolution = ? WHERE submission_id = ? AND resolved_at IS NULL")
        .bind(iso(ctx.now()), `${decision}: ${note}`, id),
    ];
    let grants = false;
    if (decision === "accept" && s.access_eligible) {
      const keys = (await db.prepare("SELECT card_id FROM readings WHERE submission_id = ?").bind(id).all<{ card_id: string }>()).results.map((r) => r.card_id);
      const since = iso(ctx.now() - ctx.cfg.CARD_UNLOCK_DAYS * 86_400_000);
      let used = false;
      for (const k of keys) {
        if (await db.prepare("SELECT 1 FROM card_unlocks WHERE card_id = ? AND account_id != ? AND unlocked_at >= ?").bind(k, s.account_id, since).first()) used = true;
      }
      if (!used) {
        grants = true;
        stmts.push(db.prepare("UPDATE submissions SET grants_access = 1 WHERE id = ?").bind(id), ...grantAccess(ctx, s.account_id, id, keys));
      }
    }
    await db.batch(stmts);
    await audit(ctx, `submission_${decision}`, id, note);
    return json({ ok: true, status: newStatus, grants_access: grants });
  }

  if (section === "accounts" && id && method === "GET" && !action) {
    const a = await accountByIdOrLogin(ctx, id);
    const subs = (await db.prepare("SELECT id, received_at, status, grants_access, decision_reason FROM submissions WHERE account_id = ? ORDER BY received_at DESC LIMIT 50").bind(a.id).all()).results;
    const nets = (await db.prepare("SELECT day, COUNT(*) AS networks FROM request_networks WHERE account_id = ? GROUP BY day ORDER BY day DESC LIMIT 14").bind(a.id).all()).results;
    const tokens = (await db.prepare("SELECT created_at, revoked_at, revoked_reason FROM tokens WHERE account_id = ? ORDER BY created_at DESC LIMIT 10").bind(a.id).all()).results;
    return json({ account: a, submissions: subs, networks_per_day: nets, tokens });
  }
  if (section === "accounts" && id && action === "quarantine" && method === "POST") {
    const a = await accountByIdOrLogin(ctx, id);
    const body = await readJson(ctx.request, 10_000);
    const on = body.on !== false;
    await db.prepare("UPDATE accounts SET status = ? WHERE id = ?").bind(on ? "quarantined" : "active", a.id).run();
    await audit(ctx, on ? "quarantine" : "unquarantine", a.id, String(body.note ?? ""));
    return json({ ok: true, status: on ? "quarantined" : "active" });
  }
  if (section === "accounts" && id && action === "revoke" && method === "POST") {
    const a = await accountByIdOrLogin(ctx, id);
    const body = await readJson(ctx.request, 10_000);
    await revokeTokens(ctx, a.id, `admin: ${String(body.note ?? "")}`, "admin");
    return json({ ok: true });
  }
  throw new ApiError(404, "not_found");
}
