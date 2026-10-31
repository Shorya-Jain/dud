// Test doubles: D1 on node:sqlite, R2 in memory, a fake GitHub and a fake clock.
// They also power the local dev server (dev.ts).

import { readFileSync, readdirSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createApp } from "../src/app.ts";
import type { GithubUser } from "../src/auth.ts";
import { merkleRoot, productRef, proofFor, digestOf, type ChallengeParams } from "../src/chalmath.ts";
import { b64encode } from "../src/crypto.ts";
import type { D1Database, D1Prepared, Env, R2Bucket } from "../src/env.ts";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

class Stmt implements D1Prepared {
  db: DatabaseSync;
  sql: string;
  args: unknown[];
  constructor(db: DatabaseSync, sql: string, args: unknown[] = []) {
    this.db = db;
    this.sql = sql;
    this.args = args;
  }
  bind(...values: unknown[]): D1Prepared {
    return new Stmt(this.db, this.sql, values);
  }
  async first<T>(): Promise<T | null> {
    return ((this.db.prepare(this.sql).get(...(this.args as any[])) as T) ?? null);
  }
  async all<T>(): Promise<{ results: T[] }> {
    return { results: this.db.prepare(this.sql).all(...(this.args as any[])) as T[] };
  }
  async run(): Promise<unknown> {
    return this.db.prepare(this.sql).run(...(this.args as any[]));
  }
  runSync() {
    this.db.prepare(this.sql).run(...(this.args as any[]));
  }
}

export class FakeD1 implements D1Database {
  db = new DatabaseSync(":memory:");
  constructor() {
    const dir = join(ROOT, "server", "migrations");
    for (const f of readdirSync(dir).sort()) this.db.exec(readFileSync(join(dir, f), "utf8"));
  }
  prepare(sql: string): D1Prepared {
    return new Stmt(this.db, sql);
  }
  async batch(statements: D1Prepared[]): Promise<unknown[]> {
    this.db.exec("BEGIN");
    try {
      for (const s of statements) (s as Stmt).runSync();
      this.db.exec("COMMIT");
    } catch (e) {
      this.db.exec("ROLLBACK");
      throw e;
    }
    return [];
  }
}

export class FakeR2 implements R2Bucket {
  objects = new Map<string, Uint8Array>();
  async put(key: string, value: Uint8Array | string) {
    this.objects.set(key, typeof value === "string" ? new TextEncoder().encode(value) : value);
  }
  async get(key: string) {
    const v = this.objects.get(key);
    return v ? { arrayBuffer: async () => v.slice().buffer } : null;
  }
}

// Fake GitHub: a token "gh:<id>:<login>:<created_at>" is valid.
export async function fakeGithub(_env: Env, token: string): Promise<GithubUser | null> {
  const m = /^gh:(\d+):([\w-]+):(.+)$/.exec(token);
  return m ? { id: Number(m[1]), login: m[2], created_at: m[3] } : null;
}

export const TINY: ChallengeParams = { m: 4, n: 3, k: 8, pool: 2, batch: 2 };

export function makeEnv(vars: Record<string, unknown> = {}): Env {
  return {
    DB: new FakeD1(),
    RAW: new FakeR2(),
    GITHUB_CLIENT_ID: "Iv1.test",
    GITHUB_CLIENT_SECRET: "secret",
    CARD_ID_PEPPER: "pepper-for-tests",
    ADMIN_TOKEN: "admin-token-for-tests-0123456789abcdef",
    REQUIRE_LOAD: "false",
    CHALLENGE_OVERRIDE: JSON.stringify({ params: TINY, count: 6, min_ms: 1000, max_ms: 120000, samples_per_gpu: 2 }),
    ...vars,
  };
}

export class Harness {
  env: Env;
  t: number;
  network = "13335:US";
  app: ReturnType<typeof createApp>;
  constructor(vars: Record<string, unknown> = {}, start = Date.parse("2026-10-31T12:00:00Z")) {
    this.env = makeEnv(vars);
    this.t = start;
    this.app = createApp({ verifyGithub: fakeGithub, now: () => this.t, networkOf: () => this.network });
  }
  async call(method: string, path: string, body?: unknown, token?: string): Promise<{ status: number; body: any }> {
    const headers: Record<string, string> = { "content-type": "application/json", "cf-connecting-ip": "203.0.113.7" };
    if (token) headers.authorization = `Bearer ${token}`;
    const res = await this.app.fetch(
      new Request(`https://registry.test${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }),
      this.env,
    );
    const text = await res.text();
    return { status: res.status, body: text ? JSON.parse(text) : null };
  }
  async login(id = 1, login = "alice", created = "2015-01-01T00:00:00Z"): Promise<string> {
    const r = await this.call("POST", "/v1/auth/github", { github_token: `gh:${id}:${login}:${created}` });
    if (r.status !== 200) throw new Error(JSON.stringify(r.body));
    return r.body.token;
  }
  sql(query: string, ...args: unknown[]) {
    return (this.env.DB as FakeD1).db.prepare(query).all(...(args as any[]));
  }
}

export function loadDoc(path: string): any {
  return JSON.parse(readFileSync(join(ROOT, path), "utf8"));
}

export function serverFixture(name: string): any {
  return loadDoc(`server/test/fixtures/${name}.json`);
}

export function gpusOf(doc: any) {
  return doc.gpus.map((g: any) => ({
    gpu_index: g.index,
    card_id: g.card.uuid_sha256.value,
    model_key: g.identity.model_key.value,
  }));
}

// The honest client: compute every digest, commit, reveal the picked products.
export async function solveChallenge(h: Harness, token: string, doc: any, opts: { commitAfterMs?: number; corrupt?: "proof" | "product" } = {}) {
  const created = await h.call("POST", "/v1/challenges", { gpus: gpusOf(doc) }, token);
  if (created.status !== 200) return { created };
  const c = created.body;
  const trees: Record<number, { digests: number[]; levels: Uint8Array[][]; root: string }> = {};
  for (const r of c.rounds) {
    const digests = [];
    for (let j = 0; j < r.count; j++) digests.push(digestOf(r.seed, j, productRef(r.seed, j, r.params), r.params));
    const { root, levels } = await merkleRoot(digests);
    trees[r.gpu_index] = { digests, levels, root };
  }
  h.t += opts.commitAfterMs ?? 5000;
  const commit = await h.call("POST", `/v1/challenges/${c.challenge_id}/commit`,
    { roots: c.rounds.map((r: any) => ({ gpu_index: r.gpu_index, merkle_root: trees[r.gpu_index].root })) }, token);
  if (commit.status !== 200) return { created, commit };
  let last: any = null;
  for (const s of commit.body.samples) {
    const r = c.rounds.find((x: any) => x.gpu_index === s.gpu_index);
    const product = productRef(r.seed, s.j, r.params);
    if (opts.corrupt === "product") product[0] += 1;
    const bytes = new Uint8Array(product.buffer.slice(0));
    const proof = proofFor(trees[s.gpu_index].levels, s.j);
    if (opts.corrupt === "proof") proof[0] = "0".repeat(64);
    last = await h.call("POST", `/v1/challenges/${c.challenge_id}/reveal`,
      { gpu_index: s.gpu_index, j: s.j, digest: trees[s.gpu_index].digests[s.j], proof, product_b64: b64encode(bytes) }, token);
    if (last.status !== 200) break;
  }
  return { created, commit, reveal: last, challenge: { challenge_id: c.challenge_id, nonce: c.nonce } };
}

// Run the full flow for one result file. The clock follows the times in the file.
export async function fullFlow(h: Harness, token: string, doc: any, opts: { commitAfterMs?: number } = {}) {
  h.t = Date.parse(doc.run.started_at) + 60_000;
  const ch = await solveChallenge(h, token, doc, opts);
  if (!ch.challenge || ch.reveal?.status !== 200) return { ch, submit: null };
  doc.challenge = ch.challenge;
  h.t = Date.parse(doc.run.finished_at) + 10_000;
  const submit = await h.call("POST", "/v1/submissions", doc, token);
  return { ch, submit };
}

export function series(n: number, f: (i: number) => Record<string, number>) {
  const s: Record<string, number[]> = { t_s: [], sm_clock_mhz: [], mem_clock_mhz: [], temp_c: [], power_w: [], util_pct: [], throttle_mask: [] };
  for (let i = 0; i < n; i++) {
    const v = f(i);
    s.t_s.push(i);
    for (const k of Object.keys(v)) s[k].push(v[k]);
  }
  return { interval_s: 1, minutes: n / 60, series: s };
}

export function plausibleLoad(minutes = 2) {
  return series(minutes * 60, (i) => ({
    sm_clock_mhz: 1980 - (i % 7) * 15, mem_clock_mhz: 2619, temp_c: 35 + Math.min(40, i / 3) + (i % 3) * 0.3,
    power_w: 640 + ((i * 37) % 50), util_pct: 100, throttle_mask: i > 60 ? 4 : 0,
  }));
}
