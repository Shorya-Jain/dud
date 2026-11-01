// Bindings, settings and the small parts of the D1 and R2 APIs that dud uses.

export interface D1Result<T> { results: T[] }
export interface D1Prepared {
  bind(...values: unknown[]): D1Prepared;
  first<T = Record<string, any>>(): Promise<T | null>;
  all<T = Record<string, any>>(): Promise<D1Result<T>>;
  run(): Promise<unknown>;
}
export interface D1Database {
  prepare(sql: string): D1Prepared;
  batch(statements: D1Prepared[]): Promise<unknown[]>;
}
export interface R2Bucket {
  put(key: string, value: Uint8Array | string, options?: unknown): Promise<unknown>;
  get(key: string): Promise<{ arrayBuffer(): Promise<ArrayBuffer> } | null>;
}

export interface Env {
  DB: D1Database;
  // Optional. Without it, the registry keeps no copy of submitted documents (only readings and raw hashes).
  RAW?: R2Bucket;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  CARD_ID_PEPPER: string;
  ADMIN_TOKEN: string;
  [setting: string]: unknown;
}

// Defaults. Override any of these in wrangler.toml [vars].
const DEFAULTS = {
  ACCESS_DAYS: 30,
  DAILY_LOOKUP_QUOTA: 100,
  CHALLENGE_TTL_HOURS: 3,
  CHALLENGES_PER_DAY: 10,
  SUBMISSIONS_PER_DAY: 10,
  LOGINS_PER_IP_PER_DAY: 30,
  REVEAL_DEADLINE_MINUTES: 30,
  CARD_UNLOCK_DAYS: 30,
  NEW_GITHUB_ACCOUNT_DAYS: 30,
  INITIAL_TRUST: 0.2,
  CONTRIBUTOR_CAP: 0.1,
  STATS_MIN_CARDS: 20,
  SHARE_FLAG_NETWORKS: 6,
  SHARE_REVOKE_NETWORKS: 12,
  MAX_SUBMISSION_MB: 40,
  REQUIRE_LOAD: true,
  ACCESS_REQUIRES_ALL_GPUS: true,
  ALLOW_MOCK: false,
};

export type Config = typeof DEFAULTS & { CHALLENGE_OVERRIDE: Record<string, any> | null };

export function config(env: Env): Config {
  const out: Record<string, any> = { ...DEFAULTS };
  for (const [key, def] of Object.entries(DEFAULTS)) {
    const v = env[key];
    if (v === undefined || v === null || v === "") continue;
    out[key] = typeof def === "boolean" ? String(v) === "true" : Number(v);
  }
  out.CHALLENGE_OVERRIDE = typeof env.CHALLENGE_OVERRIDE === "string" && env.CHALLENGE_OVERRIDE
    ? JSON.parse(env.CHALLENGE_OVERRIDE) : (env.CHALLENGE_OVERRIDE ?? null);
  return out as Config;
}

// The current time. Tests replace it.
export type Clock = () => number;
export const realClock: Clock = () => Date.now();

export function iso(ms: number): string {
  return new Date(ms).toISOString();
}

export function day(ms: number): string {
  return iso(ms).slice(0, 10);
}
