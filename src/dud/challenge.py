"""The registry challenge: GPU work that the server can spot-check.

See docs/DESIGN.md, "Challenge". The server has the same rules in
server/src/chalmath.ts. fixtures/challenge_vectors.json keeps both the same.

Summary:
- For each GPU, seed = first 4 bytes of SHA-256("dud-challenge-v1:<nonce>:<card ID>").
- Product j: C_j = (A[a_j] * t_j) @ B[b_q], with q = j // batch. A and B come
  from a pool. Entries are -1, 0 or 1, so every result is an exact integer.
- digest_j = sum over (i, c) of mix32((C_j[i,c] + 32768) ^ idx_key[i,c] ^ salt_j), mod 2^32.
- The client sends a Merkle root of all digests. The server then picks
  products. The client sends each picked C_j, its digest and a Merkle proof.
  The server checks C_j with a Freivalds test and checks the digest.
"""
from __future__ import annotations

import base64
import hashlib
import struct
import time

M32 = 0xFFFFFFFF
VALUE_OFFSET = 32768
C1, C2 = 0x7FEB352D, 0x2C1B3C6D  # Both below 2^31, so x * C fits in int64 for x < 2^32.

TAG_A, TAG_B, TAG_PICK_A, TAG_PICK_B, TAG_SIGN, TAG_SALT, TAG_INDEX = 1, 2, 3, 4, 5, 6, 7


def mix32(x: int) -> int:
    x &= M32
    x ^= x >> 16
    x = (x * C1) & M32
    x ^= x >> 15
    x = (x * C2) & M32
    x ^= x >> 16
    return x


def h(seed: int, *parts: int) -> int:
    x = seed & M32
    for p in parts:
        x = mix32(x ^ mix32(p))
    return x


def seed_for(nonce: str, card_id: str) -> int:
    d = hashlib.sha256(f"dud-challenge-v1:{nonce}:{card_id}".encode()).digest()
    return struct.unpack(">I", d[:4])[0]


def entry(base: int, idx: int) -> int:
    return mix32(idx ^ base) % 3 - 1


def sign(base: int, idx: int) -> int:
    return 1 - 2 * (mix32(idx ^ base) & 1)


def plan(seed: int, j: int, p: dict) -> tuple[int, int]:
    """(pool index of A, pool index of B) for product j."""
    return h(seed, TAG_PICK_A, j) % p["pool"], h(seed, TAG_PICK_B, j // p["batch"]) % p["pool"]


# --- Pure-Python reference (small sizes only: tests and mock mode) -----------

def product_ref(seed: int, j: int, p: dict) -> list:
    m, n, k = p["m"], p["n"], p["k"]
    a, b = plan(seed, j, p)
    base_a, base_b, base_t = h(seed, TAG_A, a), h(seed, TAG_B, b), h(seed, TAG_SIGN, j)
    t = [sign(base_t, kk) for kk in range(k)]
    A = [[entry(base_a, i * k + kk) * t[kk] for kk in range(k)] for i in range(m)]
    B = [[entry(base_b, kk * n + c) for c in range(n)] for kk in range(k)]
    return [[sum(A[i][kk] * B[kk][c] for kk in range(k)) for c in range(n)] for i in range(m)]


def digest_of(seed: int, j: int, C: list, p: dict) -> int:
    n = p["n"]
    base_idx, salt = h(seed, TAG_INDEX), h(seed, TAG_SALT, j)
    total = 0
    for i, row in enumerate(C):
        for c, v in enumerate(row):
            total += mix32(((v + VALUE_OFFSET) ^ mix32((i * n + c) ^ base_idx) ^ salt))
    return total & M32


def digests_ref(seed: int, p: dict, count: int) -> list:
    return [digest_of(seed, j, product_ref(seed, j, p), p) for j in range(count)]


# --- Merkle tree over digests ------------------------------------------------

def _sha(*parts: bytes) -> bytes:
    return hashlib.sha256(b"".join(parts)).digest()


def leaf(j: int, d: int) -> bytes:
    return _sha(b"L", struct.pack(">II", j, d))


EMPTY = _sha(b"E")


def merkle_levels(digests: list) -> list:
    level = [leaf(j, d) for j, d in enumerate(digests)]
    size = 1
    while size < len(level):
        size *= 2
    level += [EMPTY] * (size - len(level))
    levels = [level]
    while len(level) > 1:
        level = [_sha(b"N", level[i], level[i + 1]) for i in range(0, len(level), 2)]
        levels.append(level)
    return levels


def merkle_proof(levels: list, j: int) -> list:
    proof = []
    for level in levels[:-1]:
        proof.append(level[j ^ 1].hex())
        j //= 2
    return proof


def encode_product(C: list) -> str:
    """Row-major int16 little-endian, then base64."""
    flat = [v for row in C for v in row]
    return base64.b64encode(struct.pack(f"<{len(flat)}h", *flat)).decode("ascii")


# --- GPU runner (PyTorch) ----------------------------------------------------

class TorchRunner:
    """Runs the challenge on one GPU. Import torch only when a real GPU run starts."""

    def __init__(self, device_index: int):
        import torch

        self.torch = torch
        self.dev = torch.device(f"cuda:{device_index}")
        # Exact integer results need FP32 accumulation.
        torch.backends.cuda.matmul.allow_fp16_reduced_precision_reduction = False

    def _mix32(self, x):
        x = x ^ (x >> 16)
        x = (x * C1) & M32
        x = x ^ (x >> 15)
        x = (x * C2) & M32
        return x ^ (x >> 16)

    def _matrix(self, base: int, rows: int, cols: int):
        torch = self.torch
        idx = torch.arange(rows * cols, device=self.dev, dtype=torch.int64)
        return (self._mix32(idx ^ base) % 3 - 1).to(torch.float16).view(rows, cols)

    def _h(self, seed: int, tag: int, j):
        """h(seed, tag, j) for a tensor of j values. Same result as h() in Python."""
        return self._mix32(h(seed, tag) ^ self._mix32(j))

    def _signs(self, bases, k: int):
        torch = self.torch
        idx = torch.arange(k, device=self.dev, dtype=torch.int64)
        return (1 - 2 * (self._mix32(idx[None, :] ^ bases[:, None]) & 1)).to(torch.float16)

    def products(self, seed: int, start: int, end: int, p: dict, pools):
        """C for products start..end-1 (all in one batch). Returns an (end-start, m, n) float16 tensor."""
        torch = self.torch
        A_pool, B_pool = pools
        j = torch.arange(start, end, device=self.dev, dtype=torch.int64)
        a_idx = self._h(seed, TAG_PICK_A, j) % p["pool"]
        b = plan(seed, start, p)[1]
        t = self._signs(self._h(seed, TAG_SIGN, j), p["k"])
        A = A_pool[a_idx] * t[:, None, :]
        return torch.matmul(A, B_pool[b])

    def pools(self, seed: int, p: dict):
        torch = self.torch
        A = torch.stack([self._matrix(h(seed, TAG_A, i), p["m"], p["k"]) for i in range(p["pool"])])
        B = torch.stack([self._matrix(h(seed, TAG_B, i), p["k"], p["n"]) for i in range(p["pool"])])
        return A, B

    def run(self, seed: int, p: dict, count: int) -> list:
        torch = self.torch
        with torch.cuda.device(self.dev):
            pools = self.pools(seed, p)
            idx = torch.arange(p["m"] * p["n"], device=self.dev, dtype=torch.int64)
            idx_key = self._mix32(idx ^ h(seed, TAG_INDEX)).view(p["m"], p["n"])
            salts = self._h(seed, TAG_SALT, torch.arange(count, device=self.dev, dtype=torch.int64))
            out = torch.empty(count, device=self.dev, dtype=torch.int64)
            # Batches start at multiples of p["batch"], so all products in a batch use the same B.
            for start in range(0, count, p["batch"]):
                end = min(start + p["batch"], count)
                C = self.products(seed, start, end, p, pools)
                x = (C.to(torch.int64) + VALUE_OFFSET) ^ idx_key[None] ^ salts[start:end, None, None]
                out[start:end] = self._mix32(x).sum(dim=(1, 2)) & M32
            torch.cuda.synchronize(self.dev)
            return [int(v) for v in out.cpu().tolist()]

    def product(self, seed: int, j: int, p: dict) -> list:
        with self.torch.cuda.device(self.dev):
            C = self.products(seed, j, j + 1, p, self.pools(seed, p))[0]
            return C.to(self.torch.int64).cpu().tolist()


class ReferenceRunner:
    """Pure Python. For mock mode and for tests with small sizes."""

    def run(self, seed: int, p: dict, count: int) -> list:
        return digests_ref(seed, p, count)

    def product(self, seed: int, j: int, p: dict) -> list:
        return product_ref(seed, j, p)


def self_test(runner) -> bool:
    """Compare the runner with the reference on small sizes before real work."""
    p = {"m": 4, "n": 4, "k": 32, "pool": 2, "batch": 4}
    seed = seed_for("self-test", "0" * 64)
    return runner.run(seed, p, 6) == digests_ref(seed, p, 6) and runner.product(seed, 5, p) == product_ref(seed, 5, p)


def run_rounds(rounds: list, runners: dict) -> tuple[list, dict]:
    """Compute digests and Merkle roots for every GPU round.

    rounds: [{gpu_index, seed, params, count}] from the server.
    Returns (commit list for the server, saved state for the reveal step).
    """
    import threading

    results, errors = {}, []

    def work(r):
        try:
            results[r["gpu_index"]] = runners[r["gpu_index"]].run(r["seed"], r["params"], r["count"])
        except Exception as e:  # Reported after all threads stop.
            errors.append(e)

    t0 = time.monotonic()
    threads = [threading.Thread(target=work, args=(r,)) for r in rounds]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    commits, state = [], {"elapsed_s": round(time.monotonic() - t0, 3), "levels": {}}
    for r in rounds:
        levels = merkle_levels(results[r["gpu_index"]])
        state["levels"][r["gpu_index"]] = (results[r["gpu_index"]], levels)
        commits.append({"gpu_index": r["gpu_index"], "merkle_root": levels[-1][0].hex()})
    return commits, state


def reveal(sample: dict, rounds: dict, state: dict, runners: dict) -> dict:
    """The reveal for one sample {gpu_index, j}."""
    g, j = sample["gpu_index"], sample["j"]
    r = rounds[g]
    digests, levels = state["levels"][g]
    C = runners[g].product(r["seed"], j, r["params"])
    return {"gpu_index": g, "j": j, "digest": digests[j], "proof": merkle_proof(levels, j),
            "product_b64": encode_product(C)}
