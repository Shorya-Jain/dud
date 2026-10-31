import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import * as cm from "../src/chalmath.ts";
import { b64decode, gunzip } from "../src/crypto.ts";
import { checkLoad } from "../src/load.ts";
import { identify } from "../src/models.ts";
import { validate } from "../src/schema.ts";
import { parseSmi, smiTimestampMs } from "../src/smi.ts";
import { capWeights, compare, weightedPercentile } from "../src/trust.ts";
import { parseXml, XmlError } from "../src/xml.ts";
import { loadDoc, plausibleLoad, ROOT, series, serverFixture } from "./fakes.ts";

const V = loadDoc("fixtures/challenge_vectors.json");
const SCHEMA = loadDoc("src/dud/schema/result.v1.json");
const FIXTURES = ["h100_sxm_healthy", "h100_sxm_pending_remap", "a100_80gb_pcie", "container_ecc_hidden"];

test("challenge math matches Python", async () => {
  for (const [x, y] of V.mix32) assert.equal(cm.mix32(x), y);
  for (const [args, y] of V.h) assert.equal(cm.h(...(args as [number, ...number[]])), y);
  assert.equal(await cm.seedFor(V.nonce, V.card_id), V.seed);
  for (let j = 0; j < 5; j++) assert.deepEqual(cm.plan(V.seed, j, V.params), V.plans[j]);
  const C = cm.productRef(V.seed, 3, V.params);
  assert.deepEqual(Array.from(C), V.product_j3);
  assert.deepEqual(Array.from(cm.decodeProduct(V.product_j3_b64, V.params)!), V.product_j3);
  for (let j = 0; j < 5; j++) assert.equal(cm.digestOf(V.seed, j, cm.productRef(V.seed, j, V.params), V.params), V.digests[j]);
  const { root } = await cm.merkleRoot(V.digests);
  assert.equal(root, V.merkle_root);
  assert.ok(await cm.verifyProof(V.merkle_root, 3, V.digests[3], V.proof_j3, 5));
  assert.ok(!(await cm.verifyProof(V.merkle_root, 3, V.digests[3] + 1, V.proof_j3, 5)));
  assert.ok(!(await cm.verifyProof(V.merkle_root, 2, V.digests[3], V.proof_j3, 5)));
});

test("Freivalds accepts the true product and rejects a changed one", () => {
  const r = new Float64Array(V.params.n).map(() => Math.floor(Math.random() * 65536));
  const C = cm.productRef(V.seed, 4, V.params);
  assert.ok(cm.freivalds(V.seed, 4, C, V.params, r));
  C[5] += 1;
  assert.ok(!cm.freivalds(V.seed, 4, C, V.params, r));
  assert.equal(cm.decodeProduct("AAAA", V.params), null);
});

test("XML parser", () => {
  const x = parseXml('<?xml version="1.0" ?>\n<!DOCTYPE a SYSTEM "a.dtd">\n<a id="1"><!-- c --><b>x &amp; y</b><c/></a>');
  assert.equal(x.tag, "a");
  assert.equal(x.attrs.id, "1");
  assert.equal(x.children[0].text, "x & y");
  assert.equal(x.children[1].tag, "c");
  assert.throws(() => parseXml("<a><b></a>"), XmlError);
  assert.throws(() => parseXml("<a></a><b></b>"), XmlError);
  assert.throws(() => parseXml("<a>" + "<b>".repeat(40) + "</b>".repeat(40) + "</a>"), XmlError);
});

test("schema validator accepts every fixture and rejects bad documents", () => {
  for (const name of FIXTURES) assert.deepEqual(validate(SCHEMA, serverFixture(name)), [], name);
  const doc = serverFixture("h100_sxm_pending_remap");
  doc.gpus[0].history.row_remap.pending.status = "blocked";
  assert.ok(validate(SCHEMA, doc).some((e) => e.includes("must be null")));
  const doc2 = serverFixture("h100_sxm_pending_remap");
  doc2.gpus[0].card.uuid_sha256.value = "GPU-raw";
  assert.ok(validate(SCHEMA, doc2).length > 0);
  const doc3 = serverFixture("h100_sxm_pending_remap");
  doc3.extra = 1;
  assert.ok(validate(SCHEMA, doc3).some((e) => e.includes("unknown key extra")));
});

async function smiOf(doc: any) {
  const e = doc.raw.find((r: any) => r.id === "smi_q_x");
  return parseSmi(new TextDecoder().decode(await gunzip(b64decode(e.content))));
}

test("server XML reading matches the Python parser on every fixture", async () => {
  for (const name of FIXTURES) {
    const doc = serverFixture(name);
    const smi = await smiOf(doc);
    assert.equal(smi.gpus.length, doc.gpus.length);
    for (const g of doc.gpus) {
      const s = smi.gpus.find((x) => x.uuid_sha256 === g.card.uuid_sha256.value)!;
      assert.ok(s, `${name}: card ID`);
      assert.equal(s.raw_uuid_present, false);
      for (const [path, v] of Object.entries(s.values)) {
        const f = path.split(".").reduce((o: any, k) => o[k], g);
        if (f.source === "nvml") continue;
        assert.equal(v.ok, f.status === "ok", `${name} GPU ${g.index} ${path} status`);
        if (v.ok) assert.equal(v.value, f.value, `${name} GPU ${g.index} ${path}`);
      }
    }
  }
});

test("nvidia-smi time", () => {
  assert.equal(smiTimestampMs("Sat Oct 31 12:00:00 2026", 0), Date.parse("2026-10-31T12:00:00Z"));
  assert.equal(smiTimestampMs("Sat Oct 31 12:00:00 2026", -25200), Date.parse("2026-10-31T19:00:00Z"));
  assert.equal(smiTimestampMs("yesterday", 0), null);
});

test("model names match src/dud/gpumodels.py", () => {
  const py = readFileSync(join(ROOT, "src/dud/gpumodels.py"), "utf8");
  const pairs = [...py.matchAll(/\(r"([^"]+)", GpuModel\("([^"]+)"/g)].map((m) => [m[1], m[2]]);
  assert.ok(pairs.length >= 9);
  for (const [pattern, key] of pairs) {
    for (const name of pattern.split("|")) assert.equal(identify(`NVIDIA ${name}`), key, name);
  }
  assert.equal(identify("NVIDIA GeForce RTX 4090"), null);
});

test("load physics", () => {
  const limits = { default_w: 700, max_w: 700, max_sm_mhz: 1980 };
  assert.deepEqual(checkLoad(plausibleLoad(), limits), []);
  const flat = series(120, () => ({ sm_clock_mhz: 1980, mem_clock_mhz: 2619, temp_c: 60, power_w: 650, util_pct: 100, throttle_mask: 0 }));
  const p = checkLoad(flat, limits);
  assert.ok(p.some((x) => x.includes("power does not change")));
  assert.ok(p.some((x) => x.includes("temperature does not change")));
  const idle = series(120, (i) => ({ sm_clock_mhz: 345, mem_clock_mhz: 2619, temp_c: 30 + i / 20, power_w: 70 + (i % 5), util_pct: 2, throttle_mask: 0 }));
  assert.ok(checkLoad(idle, limits).some((x) => x.includes("median power")));
  const jump = plausibleLoad();
  jump.series.temp_c[50] += 30;
  assert.ok(checkLoad(jump, limits).some((x) => x.includes("jumps")));
  const short = plausibleLoad();
  short.minutes = 15;
  assert.ok(checkLoad(short, limits).some((x) => x.includes("samples")));
});

test("trust and weights", () => {
  const base = { account_id: "a", observed_at: "2026-10-02", model_key: "H100-SXM5-80GB", memory_total_mib: 81559,
                 ecc_agg_corr: 5, ecc_agg_unc: 0, remap_corr: 0, remap_unc: 0 };
  assert.equal(compare(base, []).result, "none");
  assert.equal(compare(base, [{ ...base, account_id: "b", observed_at: "2026-10-01", ecc_agg_corr: 3 }]).result, "agree");
  assert.equal(compare(base, [{ ...base, account_id: "b", observed_at: "2026-10-01", ecc_agg_corr: 9 }]).result, "disagree");
  assert.equal(compare(base, [{ ...base, account_id: "b", memory_total_mib: 40960 }]).result, "disagree");
  const items = [...Array(10)].map(() => ({ contributor: "big", weight: 1 })).concat(
    [...Array(10)].map((_, i) => ({ contributor: `c${i}`, weight: 1 })));
  const w = capWeights(items, 0.1);
  const total = w.reduce((a, b) => a + b, 0);
  assert.ok(w.slice(0, 10).reduce((a, b) => a + b, 0) <= 0.1 * total * (1 + 1e-6));
  assert.equal(weightedPercentile([1, 2, 3, 4], [1, 1, 1, 1], 0.5), 2);
  assert.equal(weightedPercentile([1, 100], [9, 1], 0.5), 1);
});

test("server messages keep sentences to 20 words (Simplified Technical English)", async () => {
  const { MESSAGES } = await import("../src/http.ts");
  for (const m of Object.values(MESSAGES))
    for (const sentence of m.split(/(?<=[.!?])\s+/)) assert.ok(sentence.split(/\s+/).length <= 20, sentence);
});
