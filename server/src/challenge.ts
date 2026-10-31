// The challenge: issue, commit (server-timed), reveal (server-checked).
// See docs/DESIGN.md, "Challenge".

import { authenticate, bump, type Ctx } from "./auth.ts";
import { decodeProduct, digestOf, freivalds, seedFor, verifyProof, type ChallengeParams } from "./chalmath.ts";
import { randomHex, randomInt } from "./crypto.ts";
import { iso } from "./env.ts";
import { ApiError, json, readJson } from "./http.ts";
import specs from "./specs.json" with { type: "json" };

export type Round = {
  gpu_index: number;
  card_id: string;
  model_key: string;
  seed: number;
  params: ChallengeParams;
  count: number;
  min_ms: number;
  max_ms: number;
};

type Sample = { gpu_index: number; j: number; done: boolean };

export type ChallengeRow = {
  id: string;
  account_id: string;
  nonce: string;
  created_ms: number;
  expires_ms: number;
  rounds_json: string;
  status: string;
  committed_ms: number | null;
  elapsed_ms: number | null;
  roots_json: string | null;
  samples_json: string | null;
  fail_reason: string | null;
  used_by: string | null;
};

const HEX64 = /^[0-9a-f]{64}$/;

export function planRound(ctx: Ctx, model_key: string): Omit<Round, "gpu_index" | "card_id" | "seed"> {
  const model = (specs.models as Record<string, any>)[model_key];
  if (!model) throw new ApiError(400, "bad_request", { detail: `dud does not know the model ${model_key}.` });
  const c = specs.challenge;
  const o = ctx.cfg.CHALLENGE_OVERRIDE ?? {};
  const params: ChallengeParams = { m: c.m, n: c.n, k: c.k, pool: c.pool, batch: c.batch, ...(o.params ?? {}) };
  const flops = 2 * params.m * params.n * params.k;
  const peak = model.fp16_dense_tflops.value * 1e12;
  const count = o.count ?? Math.max(1, Math.round((c.target_seconds * peak * c.assumed_efficiency) / flops));
  const min_ms = o.min_ms ?? (count * flops / peak) * 1000;
  const max_ms = o.max_ms ?? (count * flops / (peak * c.min_efficiency)) * 1000 + c.network_allowance_seconds * 1000;
  return { model_key, params, count, min_ms, max_ms };
}

async function loadOwned(ctx: Ctx, id: string, accountId: string): Promise<ChallengeRow> {
  const row = await ctx.env.DB.prepare("SELECT * FROM challenges WHERE id = ?").bind(id).first<ChallengeRow>();
  if (!row || row.account_id !== accountId) throw new ApiError(404, "challenge_invalid");
  if (row.expires_ms < ctx.now()) throw new ApiError(410, "challenge_invalid");
  return row;
}

async function fail(ctx: Ctx, row: ChallengeRow, reason: string): Promise<never> {
  await ctx.env.DB.prepare("UPDATE challenges SET status = 'failed', fail_reason = ? WHERE id = ?").bind(reason, row.id).run();
  throw new ApiError(422, "challenge_failed", { detail: reason });
}

export async function createChallenge(ctx: Ctx): Promise<Response> {
  const account = await authenticate(ctx);
  const body = await readJson(ctx.request, 20_000);
  const gpus = body.gpus;
  if (!Array.isArray(gpus) || gpus.length < 1 || gpus.length > 16)
    throw new ApiError(400, "bad_request", { detail: "Send 1 to 16 GPUs." });
  const seen = new Set<string>();
  for (const g of gpus) {
    if (!Number.isInteger(g.gpu_index) || g.gpu_index < 0 || typeof g.card_id !== "string" || !HEX64.test(g.card_id) ||
        typeof g.model_key !== "string")
      throw new ApiError(400, "bad_request", { detail: "Each GPU needs gpu_index, card_id and model_key." });
    if (seen.has(g.card_id) || seen.has(`i${g.gpu_index}`)) throw new ApiError(400, "bad_request", { detail: "GPUs repeat." });
    seen.add(g.card_id).add(`i${g.gpu_index}`);
  }
  await bump(ctx, account.id, "challenge", ctx.cfg.CHALLENGES_PER_DAY, "rate_limited");

  const nonce = randomHex(32);
  const rounds: Round[] = [];
  for (const g of gpus) {
    rounds.push({ gpu_index: g.gpu_index, card_id: g.card_id, seed: await seedFor(nonce, g.card_id), ...planRound(ctx, g.model_key) });
  }
  const id = "chl_" + randomHex(12);
  const now = ctx.now();
  const expires = now + ctx.cfg.CHALLENGE_TTL_HOURS * 3_600_000;
  await ctx.env.DB.prepare(
    "INSERT INTO challenges (id, account_id, nonce, created_ms, expires_ms, rounds_json, status) VALUES (?, ?, ?, ?, ?, ?, 'issued')",
  ).bind(id, account.id, nonce, now, expires, JSON.stringify(rounds)).run();
  return json({
    challenge_id: id,
    nonce,
    issued_at: iso(now),
    expires_at: iso(expires),
    rounds: rounds.map((r) => ({ gpu_index: r.gpu_index, seed: r.seed, params: r.params, count: r.count })),
  });
}

export async function commitChallenge(ctx: Ctx, id: string): Promise<Response> {
  const account = await authenticate(ctx);
  const row = await loadOwned(ctx, id, account.id);
  if (row.status !== "issued") throw new ApiError(409, "challenge_state");
  const now = ctx.now();
  const body = await readJson(ctx.request, 20_000);
  const rounds: Round[] = JSON.parse(row.rounds_json);
  const roots: Record<string, string> = {};
  for (const r of Array.isArray(body.roots) ? body.roots : []) {
    if (typeof r?.merkle_root === "string" && HEX64.test(r.merkle_root)) roots[String(r.gpu_index)] = r.merkle_root;
  }
  if (rounds.some((r) => !roots[String(r.gpu_index)])) await fail(ctx, row, "a Merkle root is missing");

  // Time from issue to commit, measured by the server clock only.
  const elapsed = now - row.created_ms;
  await ctx.env.DB.prepare("UPDATE challenges SET elapsed_ms = ?, committed_ms = ?, roots_json = ? WHERE id = ?")
    .bind(elapsed, now, JSON.stringify(roots), id).run();
  const minMs = Math.max(...rounds.map((r) => r.min_ms));
  const maxMs = Math.max(...rounds.map((r) => r.max_ms));
  if (elapsed < minMs) await fail(ctx, row, `too fast for the claimed GPU model (${elapsed} ms, minimum ${Math.round(minMs)} ms)`);
  if (elapsed > maxMs) await fail(ctx, row, `too slow for the claimed GPU model (${elapsed} ms, maximum ${Math.round(maxMs)} ms)`);

  const per = Number(ctx.cfg.CHALLENGE_OVERRIDE?.samples_per_gpu ?? specs.challenge.samples_per_gpu);
  const samples: Sample[] = [];
  for (const r of rounds) {
    const picked = new Set<number>();
    while (picked.size < Math.min(per, r.count)) picked.add(randomInt(r.count));
    for (const j of picked) samples.push({ gpu_index: r.gpu_index, j, done: false });
  }
  await ctx.env.DB.prepare("UPDATE challenges SET status = 'committed', samples_json = ? WHERE id = ?")
    .bind(JSON.stringify(samples), id).run();
  return json({
    status: "committed",
    elapsed_ms: elapsed,
    samples: samples.map(({ gpu_index, j }) => ({ gpu_index, j })),
    reveal_deadline: iso(now + ctx.cfg.REVEAL_DEADLINE_MINUTES * 60_000),
  });
}

export async function revealChallenge(ctx: Ctx, id: string): Promise<Response> {
  const account = await authenticate(ctx);
  const row = await loadOwned(ctx, id, account.id);
  if (row.status !== "committed") throw new ApiError(409, "challenge_state");
  if (ctx.now() > row.committed_ms! + ctx.cfg.REVEAL_DEADLINE_MINUTES * 60_000) await fail(ctx, row, "the reveal is too late");
  const body = await readJson(ctx.request, 20_000_000);
  const samples: Sample[] = JSON.parse(row.samples_json!);
  const sample = samples.find((s) => s.gpu_index === body.gpu_index && s.j === body.j && !s.done);
  if (!sample) throw new ApiError(400, "bad_request", { detail: "The registry did not ask for this product." });
  const round = (JSON.parse(row.rounds_json) as Round[]).find((r) => r.gpu_index === sample.gpu_index)!;
  const root = JSON.parse(row.roots_json!)[String(sample.gpu_index)];

  const digest = Number(body.digest);
  if (!Number.isInteger(digest) || digest < 0 || digest > 0xffffffff || !Array.isArray(body.proof) ||
      !(await verifyProof(root, sample.j, digest, body.proof, round.count)))
    await fail(ctx, row, "the Merkle proof does not match the commit");
  const C = typeof body.product_b64 === "string" ? decodeProduct(body.product_b64, round.params) : null;
  if (!C) await fail(ctx, row, "the product has the wrong size");
  if (digestOf(round.seed, sample.j, C!, round.params) !== digest) await fail(ctx, row, "the product does not match its digest");
  const r = new Float64Array(round.params.n);
  for (let i = 0; i < r.length; i++) r[i] = randomInt(65536);
  if (!freivalds(round.seed, sample.j, C!, round.params, r)) await fail(ctx, row, "the product is not correct");

  sample.done = true;
  const remaining = samples.filter((s) => !s.done).length;
  await ctx.env.DB.prepare("UPDATE challenges SET samples_json = ?, status = ? WHERE id = ?")
    .bind(JSON.stringify(samples), remaining === 0 ? "verified" : "committed", id).run();
  return json({ status: remaining === 0 ? "verified" : "committed", remaining });
}
