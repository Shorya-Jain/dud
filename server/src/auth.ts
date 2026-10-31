// GitHub sign-in, dud tokens, daily counters and token-sharing detection.

import { randomHex, randomToken, sha256Hex } from "./crypto.ts";
import { day, iso, type Clock, type Config, type Env } from "./env.ts";
import { ApiError, json, readJson } from "./http.ts";

export type GithubUser = { id: number; login: string; created_at: string | null };
export type GithubVerifier = (env: Env, githubToken: string) => Promise<GithubUser | null>;

export type Ctx = {
  env: Env;
  cfg: Config;
  now: Clock;
  request: Request;
  ip: string;
  network: string;
  verifyGithub: GithubVerifier;
};

export type Account = {
  id: string;
  github_id: number;
  github_login: string;
  github_created_at: string | null;
  created_at: string;
  access_until: string | null;
  trust: number;
  status: string;
};

const GH_HEADERS = { "user-agent": "dud-registry", accept: "application/vnd.github+json" };

// Production verifier. It checks that the GitHub token belongs to the dud OAuth app,
// reads the user, then revokes the GitHub token (dud does not keep it).
export const githubVerifier: GithubVerifier = async (env, token) => {
  const basic = "Basic " + btoa(`${env.GITHUB_CLIENT_ID}:${env.GITHUB_CLIENT_SECRET}`);
  const appUrl = `https://api.github.com/applications/${env.GITHUB_CLIENT_ID}/token`;
  const check = await fetch(appUrl, {
    method: "POST",
    headers: { ...GH_HEADERS, authorization: basic, "content-type": "application/json" },
    body: JSON.stringify({ access_token: token }),
  });
  if (check.status !== 200) return null;
  const user = await fetch("https://api.github.com/user", { headers: { ...GH_HEADERS, authorization: `Bearer ${token}` } });
  if (user.status !== 200) return null;
  const u: any = await user.json();
  await fetch(appUrl, {
    method: "DELETE",
    headers: { ...GH_HEADERS, authorization: basic, "content-type": "application/json" },
    body: JSON.stringify({ access_token: token }),
  }).catch(() => undefined);
  return { id: Number(u.id), login: String(u.login), created_at: u.created_at ?? null };
};

// --- Daily counters -------------------------------------------------------------

export async function usage(ctx: Ctx, subject: string, kind: string): Promise<number> {
  const row = await ctx.env.DB.prepare("SELECT count FROM daily_usage WHERE subject = ? AND day = ? AND kind = ?")
    .bind(subject, day(ctx.now()), kind).first<{ count: number }>();
  return row?.count ?? 0;
}

// Count one use. Throws 429 if the count is already at the limit.
export async function bump(ctx: Ctx, subject: string, kind: string, limit: number, code: "quota" | "rate_limited"): Promise<number> {
  const used = await usage(ctx, subject, kind);
  if (used >= limit) throw new ApiError(429, code, { quota: limit });
  await ctx.env.DB.prepare(
    "INSERT INTO daily_usage (subject, day, kind, count) VALUES (?, ?, ?, 1) " +
      "ON CONFLICT (subject, day, kind) DO UPDATE SET count = count + 1",
  ).bind(subject, day(ctx.now()), kind).run();
  return used + 1;
}

// --- Login ------------------------------------------------------------------------

export async function login(ctx: Ctx): Promise<Response> {
  await bump(ctx, `ip:${ctx.ip}`, "login", ctx.cfg.LOGINS_PER_IP_PER_DAY, "rate_limited");
  const body = await readJson(ctx.request, 10_000);
  if (typeof body.github_token !== "string" || body.github_token.length > 500)
    throw new ApiError(400, "bad_request", { detail: "Send github_token." });
  const user = await ctx.verifyGithub(ctx.env, body.github_token);
  if (!user) throw new ApiError(401, "github_failed");

  const db = ctx.env.DB;
  const now = iso(ctx.now());
  let account = await db.prepare("SELECT * FROM accounts WHERE github_id = ?").bind(user.id).first<Account>();
  if (!account) {
    const id = "acc_" + randomHex(12);
    await db.prepare(
      "INSERT INTO accounts (id, github_id, github_login, github_created_at, created_at, trust) VALUES (?, ?, ?, ?, ?, ?)",
    ).bind(id, user.id, user.login, user.created_at, now, ctx.cfg.INITIAL_TRUST).run();
    account = (await db.prepare("SELECT * FROM accounts WHERE id = ?").bind(id).first<Account>())!;
  } else {
    await db.prepare("UPDATE accounts SET github_login = ? WHERE id = ?").bind(user.login, account.id).run();
  }

  // One token per account: a new login stops the old token.
  const token = randomToken();
  await db.batch([
    db.prepare("UPDATE tokens SET revoked_at = ?, revoked_reason = 'new_login' WHERE account_id = ? AND revoked_at IS NULL")
      .bind(now, account.id),
    db.prepare("INSERT INTO tokens (token_hash, account_id, created_at) VALUES (?, ?, ?)")
      .bind(await sha256Hex(token), account.id, now),
  ]);
  return json({ token, account: publicAccount(ctx, account) });
}

export function publicAccount(ctx: Ctx, a: Account) {
  const ageDays = a.github_created_at ? (ctx.now() - Date.parse(a.github_created_at)) / 86_400_000 : 0;
  return {
    id: a.id,
    github_login: a.github_login,
    access_until: a.access_until,
    has_access: hasAccess(ctx, a),
    trust: a.trust,
    status: a.status,
    new_github_account: ageDays < ctx.cfg.NEW_GITHUB_ACCOUNT_DAYS,
  };
}

export function hasAccess(ctx: Ctx, a: Account): boolean {
  return a.status === "active" && a.access_until !== null && Date.parse(a.access_until) > ctx.now();
}

// --- Token check for every request that needs a login ---------------------------------

export async function authenticate(ctx: Ctx): Promise<Account> {
  const header = ctx.request.headers.get("authorization") ?? "";
  const m = /^Bearer (dud_[A-Za-z0-9_-]{20,100})$/.exec(header);
  if (!m) throw new ApiError(401, "unauthorized");
  const row = await ctx.env.DB.prepare(
    "SELECT a.*, t.revoked_at AS token_revoked_at, t.revoked_reason AS token_revoked_reason " +
      "FROM tokens t JOIN accounts a ON a.id = t.account_id WHERE t.token_hash = ?",
  ).bind(await sha256Hex(m[1])).first<Account & { token_revoked_at: string | null; token_revoked_reason: string | null }>();
  if (!row) throw new ApiError(401, "unauthorized");
  if (row.token_revoked_at) {
    throw new ApiError(401, row.token_revoked_reason === "new_login" ? "unauthorized" : "revoked");
  }
  await trackNetwork(ctx, row);
  return row;
}

// Token sharing: one token that many networks use on the same day.
async function trackNetwork(ctx: Ctx, a: Account): Promise<void> {
  const db = ctx.env.DB;
  const today = day(ctx.now());
  await db.prepare("INSERT OR IGNORE INTO request_networks (account_id, day, network) VALUES (?, ?, ?)")
    .bind(a.id, today, ctx.network).run();
  const n = (await db.prepare("SELECT COUNT(*) AS n FROM request_networks WHERE account_id = ? AND day = ?")
    .bind(a.id, today).first<{ n: number }>())!.n;
  if (n > ctx.cfg.SHARE_REVOKE_NETWORKS) {
    await revokeTokens(ctx, a.id, "token_sharing", "system");
    throw new ApiError(401, "revoked");
  }
  if (n === ctx.cfg.SHARE_FLAG_NETWORKS + 1) {
    await addFlag(ctx, "token_sharing_suspected", a.id, null, `${n} networks on ${today}`);
  }
}

export async function revokeTokens(ctx: Ctx, accountId: string, reason: string, actor: string): Promise<void> {
  const now = iso(ctx.now());
  await ctx.env.DB.batch([
    ctx.env.DB.prepare("UPDATE tokens SET revoked_at = ?, revoked_reason = ? WHERE account_id = ? AND revoked_at IS NULL")
      .bind(now, reason, accountId),
    ctx.env.DB.prepare("INSERT INTO audit_log (at, actor, action, target, detail) VALUES (?, ?, 'revoke_token', ?, ?)")
      .bind(now, actor, accountId, reason),
  ]);
}

export async function addFlag(ctx: Ctx, kind: string, accountId: string | null, submissionId: string | null, detail: string) {
  await ctx.env.DB.prepare(
    "INSERT INTO admin_flags (created_at, kind, account_id, submission_id, detail) VALUES (?, ?, ?, ?, ?)",
  ).bind(iso(ctx.now()), kind, accountId, submissionId, detail).run();
}

export async function requireAccess(ctx: Ctx): Promise<Account> {
  const a = await authenticate(ctx);
  if (!hasAccess(ctx, a)) throw new ApiError(403, "no_access", { days: ctx.cfg.ACCESS_DAYS });
  return a;
}
