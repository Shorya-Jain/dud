// Contributor trust and aggregate weights.
//
// - New contributors start at INITIAL_TRUST (low).
// - When a contributor's reading of a card agrees with readings from other
//   contributors of the same card, trust goes up. When it disagrees, trust goes
//   down and an admin flag is made.
// - In aggregates, one contributor can have at most CONTRIBUTOR_CAP of the weight.

export const TRUST_UP = 0.05;
export const TRUST_DOWN = 0.2;
export const LOW_TRUST = 0.5;

export type ReadingLite = {
  account_id: string;
  observed_at: string;
  model_key: string | null;
  memory_total_mib: number | null;
  ecc_agg_corr: number | null;
  ecc_agg_unc: number | null;
  remap_corr: number | null;
  remap_unc: number | null;
};

const COUNTERS: (keyof ReadingLite)[] = ["ecc_agg_corr", "ecc_agg_unc", "remap_corr", "remap_unc"];

// Compare a new reading with readings of the same card from OTHER contributors.
// Returns "agree", "disagree" or "none" (no other readings).
export function compare(mine: ReadingLite, others: ReadingLite[]): { result: "agree" | "disagree" | "none"; detail: string } {
  if (others.length === 0) return { result: "none", detail: "no readings from other contributors" };
  for (const o of others) {
    if (o.model_key !== mine.model_key || o.memory_total_mib !== mine.memory_total_mib)
      return { result: "disagree", detail: `model or memory differs from a reading of ${o.observed_at.slice(0, 10)}` };
    const earlier = o.observed_at <= mine.observed_at;
    for (const c of COUNTERS) {
      const a = mine[c] as number | null;
      const b = o[c] as number | null;
      if (a === null || b === null) continue;
      if (earlier ? a < b : a > b)
        return { result: "disagree", detail: `${c} is not in time order with a reading of ${o.observed_at.slice(0, 10)}` };
    }
  }
  return { result: "agree", detail: `agrees with ${others.length} readings from other contributors` };
}

export function nextTrust(trust: number, result: "agree" | "disagree" | "none"): number {
  if (result === "agree") return Math.min(1, trust + TRUST_UP);
  if (result === "disagree") return Math.max(0, trust - TRUST_DOWN);
  return trust;
}

// Scale weights so that no contributor has more than `cap` of the total.
export function capWeights(items: { contributor: string; weight: number }[], cap: number): number[] {
  const w = items.map((i) => i.weight);
  for (let round = 0; round < 60; round++) {
    const total = w.reduce((a, b) => a + b, 0);
    if (total <= 0) break;
    const per: Record<string, number> = {};
    items.forEach((it, i) => (per[it.contributor] = (per[it.contributor] ?? 0) + w[i]));
    let changed = false;
    for (const [c, sum] of Object.entries(per)) {
      if (sum > cap * total * (1 + 1e-9)) {
        const f = (cap * total) / sum;
        items.forEach((it, i) => { if (it.contributor === c) w[i] *= f; });
        changed = true;
      }
    }
    if (!changed) break;
  }
  return w;
}

export function weightedPercentile(values: number[], weights: number[], q: number): number | null {
  const pairs = values.map((v, i) => [v, weights[i]] as const).filter(([, w]) => w > 0).sort((a, b) => a[0] - b[0]);
  const total = pairs.reduce((a, [, w]) => a + w, 0);
  if (total <= 0) return null;
  let acc = 0;
  for (const [v, w] of pairs) {
    acc += w;
    if (acc >= q * total) return v;
  }
  return pairs[pairs.length - 1][0];
}
