// Physical checks for the sustained-load series (milestone 2 fills gpu.load).
//
// Format of gpu.load:
//   { interval_s: 1, minutes: 15,
//     series: { t_s: [], sm_clock_mhz: [], mem_clock_mhz: [], temp_c: [], power_w: [], util_pct: [], throttle_mask: [] } }
// Returns a list of problems. An empty list means the series is plausible.

const KEYS = ["t_s", "sm_clock_mhz", "mem_clock_mhz", "temp_c", "power_w", "util_pct", "throttle_mask"];

function median(xs: number[]): number {
  const s = Float64Array.from(xs).sort(); // A typed array sorts numbers without a compare function.
  return s.length ? s[Math.floor(s.length / 2)] : NaN;
}

function stdev(xs: number[]): number {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length);
}

function mean(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

export function checkLoad(load: any, limits: { default_w: number | null; max_w: number | null; max_sm_mhz: number | null }): string[] {
  const p: string[] = [];
  if (!load || typeof load !== "object" || !load.series) return ["no load series"];
  const s = load.series;
  const interval = Number(load.interval_s);
  const minutes = Number(load.minutes);
  if (!(interval > 0) || !(minutes > 0)) return ["interval_s and minutes must be positive"];
  for (const k of KEYS) if (!Array.isArray(s[k]) || s[k].some((v: unknown) => typeof v !== "number" || !isFinite(v as number)))
    return [`series ${k} is missing or has values that are not numbers`];
  const n = s.t_s.length;
  if (KEYS.some((k) => s[k].length !== n)) return ["the series have different lengths"];
  if (n < 0.9 * (minutes * 60) / interval) p.push(`only ${n} samples for ${minutes} minutes`);
  for (let i = 1; i < n; i++) {
    const dt = s.t_s[i] - s.t_s[i - 1];
    if (dt < 0.5 * interval || dt > 3 * interval) {
      p.push(`time step ${dt.toFixed(2)} s at sample ${i}`);
      break;
    }
  }
  const t: number[] = s.temp_c;
  const w: number[] = s.power_w;
  if (t.some((x) => x < 5 || x > 110)) p.push("temperature outside 5 to 110 C");
  const maxW = (limits.max_w ?? limits.default_w ?? 1000) * 1.15;
  if (w.some((x) => x < 0 || x > maxW)) p.push(`power outside 0 to ${Math.round(maxW)} W`);
  if (limits.max_sm_mhz && s.sm_clock_mhz.some((x: number) => x > limits.max_sm_mhz! * 1.05)) p.push("SM clock above the maximum clock");
  if (s.util_pct.some((x: number) => x < 0 || x > 100)) p.push("utilization outside 0 to 100 %");
  if (n < 10) return p;

  if (limits.default_w && median(w) < 0.4 * limits.default_w) p.push("median power is less than 40 % of the default power limit");
  if (median(s.util_pct) < 80) p.push("median utilization is less than 80 %");
  if (stdev(w) < 0.5) p.push("power does not change (a real GPU under load always changes)");
  if (Math.max(...t) - Math.min(...t) < 1 && stdev(t) < 0.2) p.push("temperature does not change");
  for (let i = 1; i < n; i++) {
    if (Math.abs(t[i] - t[i - 1]) > 5 * Math.max(1, s.t_s[i] - s.t_s[i - 1])) {
      p.push(`temperature jumps ${Math.abs(t[i] - t[i - 1])} C at sample ${i}`);
      break;
    }
  }
  const tenth = Math.max(1, Math.floor(n / 10));
  const start = mean(t.slice(0, tenth));
  const end = mean(t.slice(-tenth));
  if (end < start - 2) p.push("temperature falls during the load");
  if (t[0] < 70 && Math.max(...t) < t[0] + 3) p.push("temperature does not rise under load");
  return p;
}
