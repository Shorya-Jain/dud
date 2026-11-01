// The registry's own verdict for each GPU. Same rules and engine as src/dud/grade.py.
// The registry never uses the verdict that the client sends.

import grading from "./grading.json" with { type: "json" };
import specs from "./specs.json" with { type: "json" };

export type RuleResult = { rule: string; result: "pass" | "fail" | "missing" | "skipped"; text: string };
export type GpuVerdict = { verdict: "KEEP" | "KILL" | "UNKNOWN"; results: RuleResult[] };

function getPath(obj: any, path: string): any {
  return path.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

function pct(x: number): string {
  return `${Math.round(x * 100)} %`;
}

function num(x: any): string {
  if (typeof x === "number" && !Number.isInteger(x)) return Math.abs(x) < 100 ? x.toFixed(1) : x.toFixed(0);
  return String(x);
}

export function specValue(modelKey: string | null, key: string): number | null {
  const v = (specs.models as Record<string, any>)[modelKey ?? ""]?.[key];
  return v && typeof v.value === "number" ? v.value : null;
}

export function gradeGpu(gpu: any, mode: "quick" | "full"): GpuVerdict {
  let verdict: GpuVerdict["verdict"] = "KEEP";
  const results: RuleResult[] = [];
  for (const rule of grading.rules as any[]) {
    if (!rule.modes.includes(mode)) continue;
    const f = getPath(gpu, rule.value);
    let value: any = f && f.status === "ok" ? f.value : null;
    let limit: any = null;
    let spec: number | null = null;
    let ok: boolean | null = null;
    const c = rule.check;
    if (value !== null && value !== undefined) {
      if ("max" in c) { limit = c.max; ok = value <= limit; }
      else if ("is" in c) { limit = c.is; ok = value === limit; }
      else if ("not_in" in c) { limit = c.not_in; ok = !c.not_in.includes(value); }
      else if ("min_spec_fraction" in c) {
        limit = c.min_spec_fraction;
        spec = specValue(gpu?.identity?.model_key?.value ?? null, c.spec);
        if (spec) ok = value >= limit * spec;
        else value = null;
      }
    }
    let result: RuleResult["result"] = ok === null ? "missing" : ok ? "pass" : "fail";
    const fraction = spec && value !== null ? value / spec : value;
    const text = String(rule.explain[result])
      .replace("{value}", value === null || value === undefined ? "-" : num(value))
      .replace("{limit}", Array.isArray(limit) ? limit.join(", ") : num(limit))
      .replace("{value_pct}", typeof fraction === "number" ? pct(fraction) : "-")
      .replace("{limit_pct}", typeof limit === "number" ? pct(limit) : "-")
      .replace("{spec_value}", spec ? num(spec) : "-");
    if (result === "missing" && rule.if_missing === "skip") result = "skipped";
    results.push({ rule: rule.id, result, text });
    if (result === "fail" && rule.verdict === "KILL") verdict = "KILL";
    else if (result === "missing" && verdict !== "KILL") verdict = "UNKNOWN";
  }
  return { verdict, results };
}
