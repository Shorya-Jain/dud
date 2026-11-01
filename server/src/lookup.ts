// Registry reads. Each needs access, counts against the daily quota, and returns
// data for one card ID or percentiles for one model. There is no list and no export.

import { authenticate, bump, publicAccount, requireAccess, usage, type Ctx } from "./auth.ts";
import { ApiError, json } from "./http.ts";
import specs from "./specs.json" with { type: "json" };
import { cardKey } from "./submit.ts";
import { capWeights, LOW_TRUST, weightedPercentile } from "./trust.ts";

const HEX64 = /^[0-9a-f]{64}$/;

export async function me(ctx: Ctx): Promise<Response> {
  const a = await authenticate(ctx);
  return json({
    account: publicAccount(ctx, a),
    lookups_today: await usage(ctx, a.id, "lookup"),
    lookup_quota: ctx.cfg.DAILY_LOOKUP_QUOTA,
  });
}

async function countLookup(ctx: Ctx, accountId: string): Promise<number> {
  const used = await bump(ctx, accountId, "lookup", ctx.cfg.DAILY_LOOKUP_QUOTA, "quota");
  return ctx.cfg.DAILY_LOOKUP_QUOTA - used;
}

export async function lookupCard(ctx: Ctx, clientCardId: string): Promise<Response> {
  const a = await requireAccess(ctx);
  if (!HEX64.test(clientCardId)) throw new ApiError(400, "bad_request", { detail: "A card ID is 64 hexadecimal characters." });
  const left = await countLookup(ctx, a.id);
  const rows = (await ctx.env.DB.prepare(
    "SELECT r.*, acc.trust AS contributor_trust FROM readings r JOIN accounts acc ON acc.id = r.account_id " +
      "WHERE r.card_id = ? AND r.status = 'accepted' AND acc.status = 'active' ORDER BY r.observed_at",
  ).bind(await cardKey(ctx, "card", clientCardId)).all<Record<string, any>>()).results;
  return json({
    card_id: clientCardId,
    contributors: new Set(rows.map((r) => r.account_id)).size,
    readings: rows.map((r) => ({
      date: String(r.observed_at).slice(0, 10),
      model_key: r.model_key,
      provider: r.provider,
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
      trust: r.contributor_trust < LOW_TRUST ? "low" : "normal",
      yours: r.account_id === a.id,
    })),
    lookups_left_today: left,
  });
}

const METRICS: Record<string, (r: Record<string, any>) => number | null> = {
  aggregate_correctable_ecc: (r) => r.ecc_agg_corr,
  aggregate_uncorrectable_ecc: (r) => r.ecc_agg_unc,
  row_remaps_correctable: (r) => r.remap_corr,
  row_remaps_uncorrectable: (r) => r.remap_unc,
  bank_availability_max_fraction: (r) => {
    const total = [r.bank_max, r.bank_high, r.bank_partial, r.bank_low, r.bank_none];
    if (total.some((x) => x === null)) return null;
    const sum = total.reduce((a, b) => a + b, 0);
    return sum > 0 ? r.bank_max / sum : null;
  },
  xid_count: (r) => r.xid_count,
};

export async function stats(ctx: Ctx, modelKey: string, provider: string | null): Promise<Response> {
  const a = await requireAccess(ctx);
  if (!(modelKey in specs.models)) throw new ApiError(404, "not_found");
  const left = await countLookup(ctx, a.id);
  // The latest accepted reading of each card, from active contributors.
  const rows = (await ctx.env.DB.prepare(
    "SELECT r.*, acc.trust AS contributor_trust FROM readings r JOIN accounts acc ON acc.id = r.account_id " +
      "WHERE r.model_key = ? AND r.status = 'accepted' AND acc.status = 'active' " + (provider ? "AND r.provider = ? " : "") +
      "AND r.id = (SELECT r2.id FROM readings r2 WHERE r2.card_id = r.card_id AND r2.status = 'accepted' ORDER BY r2.observed_at DESC LIMIT 1)",
  ).bind(...(provider ? [modelKey, provider] : [modelKey])).all<Record<string, any>>()).results;

  const contributors = new Set(rows.map((r) => r.account_id)).size;
  const minContributors = Math.ceil(1 / ctx.cfg.CONTRIBUTOR_CAP);
  if (rows.length < ctx.cfg.STATS_MIN_CARDS || contributors < minContributors) {
    return json({ model_key: modelKey, provider, enough_data: false, lookups_left_today: left });
  }
  const weights = capWeights(rows.map((r) => ({ contributor: r.account_id, weight: r.contributor_trust })), ctx.cfg.CONTRIBUTOR_CAP);
  const percentiles: Record<string, Record<string, number | null>> = {};
  for (const [name, fn] of Object.entries(METRICS)) {
    const vals: number[] = [];
    const ws: number[] = [];
    rows.forEach((r, i) => {
      const v = fn(r);
      if (v !== null && v !== undefined) {
        vals.push(v);
        ws.push(weights[i]);
      }
    });
    percentiles[name] = {
      p10: weightedPercentile(vals, ws, 0.1),
      p50: weightedPercentile(vals, ws, 0.5),
      p90: weightedPercentile(vals, ws, 0.9),
    };
  }
  return json({ model_key: modelKey, provider, enough_data: true, percentiles, lookups_left_today: left });
}
