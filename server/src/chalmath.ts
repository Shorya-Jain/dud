// Challenge rules. Must give the same results as src/dud/challenge.py.
// fixtures/challenge_vectors.json and test/chalmath.test.ts check this.

import { b64decode, fromHex, hex, sha256 } from "./crypto.ts";

export type ChallengeParams = { m: number; n: number; k: number; pool: number; batch: number };

const VALUE_OFFSET = 32768;
const C1 = 0x7feb352d;
const C2 = 0x2c1b3c6d;
export const TAG = { A: 1, B: 2, PICK_A: 3, PICK_B: 4, SIGN: 5, SALT: 6, INDEX: 7 };

export function mix32(x: number): number {
  x = x >>> 0;
  x = (x ^ (x >>> 16)) >>> 0;
  x = Math.imul(x, C1) >>> 0;
  x = (x ^ (x >>> 15)) >>> 0;
  x = Math.imul(x, C2) >>> 0;
  return (x ^ (x >>> 16)) >>> 0;
}

export function h(seed: number, ...parts: number[]): number {
  let x = seed >>> 0;
  for (const p of parts) x = mix32((x ^ mix32(p)) >>> 0);
  return x;
}

export async function seedFor(nonce: string, cardId: string): Promise<number> {
  const d = await sha256(`dud-challenge-v1:${nonce}:${cardId}`);
  return ((d[0] << 24) | (d[1] << 16) | (d[2] << 8) | d[3]) >>> 0;
}

export function plan(seed: number, j: number, p: ChallengeParams): [number, number] {
  return [h(seed, TAG.PICK_A, j) % p.pool, h(seed, TAG.PICK_B, Math.floor(j / p.batch)) % p.pool];
}

function entry(base: number, idx: number): number {
  return (mix32((idx ^ base) >>> 0) % 3) - 1;
}

export function digestOf(seed: number, j: number, C: Int16Array, p: ChallengeParams): number {
  const baseIdx = h(seed, TAG.INDEX);
  const salt = h(seed, TAG.SALT, j);
  let total = 0;
  for (let idx = 0; idx < p.m * p.n; idx++) {
    const key = mix32((idx ^ baseIdx) >>> 0);
    total = (total + mix32(((C[idx] + VALUE_OFFSET) ^ key ^ salt) >>> 0)) >>> 0;
  }
  return total;
}

export function decodeProduct(b64: string, p: ChallengeParams): Int16Array | null {
  const bytes = b64decode(b64);
  if (bytes.length !== p.m * p.n * 2) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = new Int16Array(p.m * p.n);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true);
  return out;
}

// Freivalds test: C == (A * t) @ B, checked as C r == (A * t)(B r) for a random r.
// Integers stay below 2^53, so float64 arithmetic is exact.
export function freivalds(seed: number, j: number, C: Int16Array, p: ChallengeParams, r: Float64Array): boolean {
  const [a, b] = plan(seed, j, p);
  const baseA = h(seed, TAG.A, a);
  const baseB = h(seed, TAG.B, b);
  const baseT = h(seed, TAG.SIGN, j);
  const y = new Float64Array(p.k);
  for (let kk = 0; kk < p.k; kk++) {
    let s = 0;
    const row = kk * p.n;
    for (let c = 0; c < p.n; c++) s += entry(baseB, row + c) * r[c];
    y[kk] = s * (1 - 2 * (mix32((kk ^ baseT) >>> 0) & 1));
  }
  for (let i = 0; i < p.m; i++) {
    let z = 0;
    const row = i * p.k;
    for (let kk = 0; kk < p.k; kk++) z += entry(baseA, row + kk) * y[kk];
    let w = 0;
    const crow = i * p.n;
    for (let c = 0; c < p.n; c++) w += C[crow + c] * r[c];
    if (z !== w) return false;
  }
  return true;
}

// --- Merkle tree over digests -------------------------------------------------

function u32be(x: number): Uint8Array {
  return new Uint8Array([(x >>> 24) & 255, (x >>> 16) & 255, (x >>> 8) & 255, x & 255]);
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((s, p) => s + p.length, 0));
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

const L = new Uint8Array([0x4c]);
const N = new Uint8Array([0x4e]);

export async function leafHash(j: number, digest: number): Promise<Uint8Array> {
  return sha256(concat(L, u32be(j), u32be(digest)));
}

export async function verifyProof(root: string, j: number, digest: number, proof: string[], count: number): Promise<boolean> {
  let size = 1;
  let depth = 0;
  while (size < count) {
    size *= 2;
    depth++;
  }
  if (proof.length !== depth || j < 0 || j >= count) return false;
  let node = await leafHash(j, digest);
  let idx = j;
  for (const sib of proof) {
    if (!/^[0-9a-f]{64}$/.test(sib)) return false;
    const s = fromHex(sib);
    node = idx % 2 === 0 ? await sha256(concat(N, node, s)) : await sha256(concat(N, s, node));
    idx = Math.floor(idx / 2);
  }
  return hex(node) === root;
}

// For tests and the dev client: the full tree.
export async function merkleRoot(digests: number[]): Promise<{ root: string; levels: Uint8Array[][] }> {
  let level: Uint8Array[] = [];
  for (let j = 0; j < digests.length; j++) level.push(await leafHash(j, digests[j]));
  let size = 1;
  while (size < level.length) size *= 2;
  const empty = await sha256(new Uint8Array([0x45]));
  while (level.length < size) level.push(empty);
  const levels = [level];
  while (level.length > 1) {
    const next: Uint8Array[] = [];
    for (let i = 0; i < level.length; i += 2) next.push(await sha256(concat(N, level[i], level[i + 1])));
    level = next;
    levels.push(level);
  }
  return { root: hex(level[0]), levels };
}

export function proofFor(levels: Uint8Array[][], j: number): string[] {
  const out: string[] = [];
  for (const level of levels.slice(0, -1)) {
    out.push(hex(level[j ^ 1]));
    j = Math.floor(j / 2);
  }
  return out;
}

// Reference product, for tests and the dev client only (small sizes).
export function productRef(seed: number, j: number, p: ChallengeParams): Int16Array {
  const [a, b] = plan(seed, j, p);
  const baseA = h(seed, TAG.A, a);
  const baseB = h(seed, TAG.B, b);
  const baseT = h(seed, TAG.SIGN, j);
  const C = new Int16Array(p.m * p.n);
  for (let i = 0; i < p.m; i++)
    for (let c = 0; c < p.n; c++) {
      let s = 0;
      for (let kk = 0; kk < p.k; kk++) {
        const t = 1 - 2 * (mix32((kk ^ baseT) >>> 0) & 1);
        s += entry(baseA, i * p.k + kk) * t * entry(baseB, kk * p.n + c);
      }
      C[i * p.n + c] = s;
    }
  return C;
}
