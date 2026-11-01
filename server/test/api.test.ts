import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fullFlow, Harness, loadDoc, plausibleLoad, ROOT, serverFixture, solveChallenge, TINY } from "./fakes.ts";

const CARD = "ab".repeat(32);

test("login gives one token per account and stores only its hash", async () => {
  const h = new Harness();
  const t1 = await h.login();
  const t2 = await h.login();
  assert.match(t1, /^dud_/);
  assert.equal((await h.call("GET", "/v1/me", undefined, t1)).status, 401); // A new login stops the old token.
  const me = await h.call("GET", "/v1/me", undefined, t2);
  assert.equal(me.status, 200);
  assert.equal(me.body.account.has_access, false);
  assert.equal(me.body.lookup_quota, 100);
  const rows = h.sql("SELECT token_hash FROM tokens");
  assert.equal(rows.length, 2);
  assert.ok(rows.every((r: any) => r.token_hash !== t1 && r.token_hash !== t2 && /^[0-9a-f]{64}$/.test(r.token_hash)));
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM accounts")[0].n, 1);
  assert.equal((await h.call("POST", "/v1/auth/github", { github_token: "bad" })).status, 401);
});

test("requests without a valid token get 401; registry reads without access get 403", async () => {
  const h = new Harness();
  assert.equal((await h.call("GET", `/v1/cards/${CARD}`)).status, 401);
  assert.equal((await h.call("GET", `/v1/cards/${CARD}`, undefined, "dud_" + "x".repeat(43))).status, 401);
  const t = await h.login();
  const r = await h.call("GET", `/v1/cards/${CARD}`, undefined, t);
  assert.equal(r.status, 403);
  assert.match(r.body.message, /Run dud full/);
  assert.equal((await h.call("GET", "/v1/stats/H100-SXM5-80GB", undefined, t)).status, 403);
});

test("an honest full test is accepted and gives 30 days of access", async () => {
  const h = new Harness();
  const t = await h.login();
  const doc = serverFixture("h100_sxm_healthy");
  const { ch, submit } = await fullFlow(h, t, doc);
  assert.equal(ch.reveal.body.status, "verified");
  assert.equal(submit!.status, 200, JSON.stringify(submit!.body));
  assert.equal(submit!.body.status, "accepted");
  assert.equal(submit!.body.grants_access, true);
  assert.equal(Date.parse(submit!.body.access_until), h.t + 30 * 86_400_000);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM readings")[0].n, 8);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM card_unlocks")[0].n, 8);
  assert.equal((h.env.RAW as any).objects.size, 1);
  const checks = h.sql("SELECT check_name, result FROM submission_checks");
  assert.ok(checks.every((c: any) => c.result === "pass"), JSON.stringify(checks));
  // Card IDs are stored as HMACs, never as the client hash.
  const client = doc.gpus[0].card.uuid_sha256.value;
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM cards WHERE card_id = ?", client)[0].n, 0);

  // Lookup works for that card, counts against the quota and shows only that card.
  const look = await h.call("GET", `/v1/cards/${client}`, undefined, t);
  assert.equal(look.status, 200);
  assert.equal(look.body.readings.length, 1);
  assert.equal(look.body.readings[0].yours, true);
  assert.equal(look.body.readings[0].trust, "low");
  assert.equal(look.body.lookups_left_today, 99);
  const unknown = await h.call("GET", `/v1/cards/${CARD}`, undefined, t);
  assert.equal(unknown.body.readings.length, 0);

  // The challenge is single-use.
  const again = await h.call("POST", "/v1/submissions", doc, t);
  assert.equal(again.body.status, "rejected");
  assert.ok(again.body.checks.some((c: any) => c.name === "challenge" && c.detail.includes("used before")));

  // Access ends after 30 days.
  h.t += 31 * 86_400_000;
  assert.equal((await h.call("GET", `/v1/cards/${client}`, undefined, t)).status, 403);
});

test("every fixture node passes", async () => {
  for (const name of ["h100_sxm_pending_remap", "a100_80gb_pcie", "container_ecc_hidden"]) {
    const h = new Harness();
    const t = await h.login();
    const { submit } = await fullFlow(h, t, serverFixture(name));
    assert.equal(submit!.body.status, "accepted", `${name}: ${JSON.stringify(submit!.body)}`);
  }
});

test("the registry stores its own verdict, not the client's", async () => {
  const h = new Harness();
  const t = await h.login();
  const doc = serverFixture("a100_80gb_pcie");
  for (const g of doc.gpus) g.verdict.verdict = "KEEP"; // A client that lies about its verdict.
  const r = (await fullFlow(h, t, doc)).submit!;
  assert.equal(r.body.status, "accepted");
  const look = await h.call("GET", `/v1/cards/${doc.gpus[0].card.uuid_sha256.value}`, undefined, t);
  assert.equal(look.body.readings[0].verdict, "KILL");
  assert.ok(look.body.readings[0].verdict_reasons.some((x: string) => x.includes("Sustained BF16 performance")));
  const log = h.sql("SELECT detail FROM submission_checks WHERE check_name = 'verdict'")[0] as any;
  assert.match(log.detail, /registry: GPU 0 KILL; client: KEEP/);
});

test("the daily lookup quota gives 429", async () => {
  const h = new Harness({ DAILY_LOOKUP_QUOTA: "3" });
  const t = await h.login();
  await fullFlow(h, t, serverFixture("a100_80gb_pcie"));
  for (let i = 0; i < 3; i++) assert.equal((await h.call("GET", `/v1/cards/${CARD}`, undefined, t)).status, 200);
  const r = await h.call("GET", `/v1/cards/${CARD}`, undefined, t);
  assert.equal(r.status, 429);
  assert.match(r.body.message, /3 lookups/);
  h.t += 86_400_000;
  assert.equal((await h.call("GET", `/v1/cards/${CARD}`, undefined, t)).status, 200);
});

test("tampered fixtures", async (t) => {
  const dir = join(ROOT, "fixtures", "tampered");
  for (const name of readdirSync(dir).sort()) {
    await t.test(name, async () => {
      const expect = loadDoc(`fixtures/tampered/${name}/expect.json`);
      const vars: Record<string, string> = {};
      if (expect.challenge_min_ms)
        vars.CHALLENGE_OVERRIDE = JSON.stringify({ params: TINY, count: 6, min_ms: expect.challenge_min_ms, max_ms: 600000 });
      const h = new Harness(vars);
      const token = await h.login();
      for (const setup of expect.setup ?? []) {
        const s = await fullFlow(h, await h.login(99, "earlier-renter"), serverFixture(setup));
        assert.equal(s.submit!.body.status, "accepted", `setup ${setup}`);
      }
      const doc = loadDoc(`fixtures/tampered/${name}/result.json`);
      const { ch, submit } = await fullFlow(h, token, doc, { commitAfterMs: expect.commit_after_ms });
      if (expect.commit_error) {
        assert.equal(ch.commit.status, 422);
        assert.match(ch.commit.body.message, new RegExp(expect.commit_error));
        // A submission with the failed challenge is rejected too.
        doc.challenge = { challenge_id: ch.created.body.challenge_id, nonce: ch.created.body.nonce };
        const r = await h.call("POST", "/v1/submissions", doc, token);
        assert.equal(r.body.status, expect.status);
        assert.ok(r.body.checks.some((c: any) => c.name === expect.check), JSON.stringify(r.body));
        return;
      }
      assert.equal(submit!.body.status, expect.status, JSON.stringify(submit!.body));
      assert.ok(submit!.body.checks.some((c: any) => c.name === expect.check && c.result !== "pass"), JSON.stringify(submit!.body));
      assert.equal(submit!.body.grants_access, false);
    });
  }
});

test("challenge: a reveal after the deadline fails", async () => {
  const h = new Harness();
  const t = await h.login();
  const created = await h.call("POST", "/v1/challenges", { gpus: [{ gpu_index: 0, card_id: CARD, model_key: "A100-PCIE-80GB" }] }, t);
  h.t += 5000;
  const commit = await h.call("POST", `/v1/challenges/${created.body.challenge_id}/commit`,
    { roots: [{ gpu_index: 0, merkle_root: "0".repeat(64) }] }, t);
  assert.equal(commit.status, 200);
  h.t += 31 * 60_000;
  const s = commit.body.samples[0];
  const late = await h.call("POST", `/v1/challenges/${created.body.challenge_id}/reveal`,
    { gpu_index: 0, j: s.j, digest: 0, proof: [], product_b64: "" }, t);
  assert.equal(late.status, 422);
  assert.match(late.body.message, /too late/);
});

test("challenge: wrong proof, wrong product, too slow, wrong owner, expired", async () => {
  const doc = serverFixture("a100_80gb_pcie");
  for (const corrupt of ["proof", "product"] as const) {
    const h = new Harness();
    const t = await h.login();
    const r = await solveChallenge(h, t, doc, { corrupt });
    assert.equal(r.reveal.status, 422, corrupt);
    assert.equal(h.sql("SELECT status FROM challenges")[0].status, "failed");
  }
  const h = new Harness();
  const t = await h.login();
  const slow = await solveChallenge(h, t, doc, { commitAfterMs: 200_000 });
  assert.equal(slow.commit.status, 422);
  assert.match(slow.commit.body.message, /too slow/);

  const created = await h.call("POST", "/v1/challenges", { gpus: [{ gpu_index: 0, card_id: CARD, model_key: "A100-PCIE-80GB" }] }, t);
  const other = await h.login(2, "bob");
  assert.equal((await h.call("POST", `/v1/challenges/${created.body.challenge_id}/commit`, { roots: [] }, other)).status, 404);
  h.t += 4 * 3_600_000;
  assert.equal((await h.call("POST", `/v1/challenges/${created.body.challenge_id}/commit`, { roots: [] }, t)).status, 410);
  const bad = await h.call("POST", "/v1/challenges", { gpus: [{ gpu_index: 0, card_id: CARD, model_key: "RTX-4090" }] }, t);
  assert.equal(bad.status, 400);
});

test("challenges per day are limited", async () => {
  const h = new Harness({ CHALLENGES_PER_DAY: "2" });
  const t = await h.login();
  const body = { gpus: [{ gpu_index: 0, card_id: CARD, model_key: "A100-PCIE-80GB" }] };
  assert.equal((await h.call("POST", "/v1/challenges", body, t)).status, 200);
  assert.equal((await h.call("POST", "/v1/challenges", body, t)).status, 200);
  assert.equal((await h.call("POST", "/v1/challenges", body, t)).status, 429);
});

test("the challenge must be for the same GPUs as the result", async () => {
  const h = new Harness();
  const t = await h.login();
  const doc = serverFixture("container_ecc_hidden");
  const one = { ...doc, gpus: [doc.gpus[0]] };
  h.t = Date.parse(doc.run.started_at) + 60_000;
  const ch = await solveChallenge(h, t, one);
  doc.challenge = ch.challenge;
  h.t = Date.parse(doc.run.finished_at);
  const r = await h.call("POST", "/v1/submissions", doc, t);
  assert.equal(r.body.status, "rejected");
  assert.ok(r.body.checks.some((c: any) => c.name === "card_ids"));
});

test("a card unlocks access for only one account in 30 days", async () => {
  const h = new Harness();
  const alice = await h.login(1, "alice");
  const bob = await h.login(2, "bob");
  assert.equal((await fullFlow(h, alice, serverFixture("a100_80gb_pcie"))).submit!.body.grants_access, true);
  // The fixture XML is the same file, so delete the replay record: act as if Bob's run made a new XML.
  h.sql("DELETE FROM raw_hashes");
  const r = (await fullFlow(h, bob, serverFixture("a100_80gb_pcie"))).submit!;
  assert.equal(r.body.status, "accepted");
  assert.equal(r.body.grants_access, false);
  assert.match(r.body.reason, /another account/);
  // Alice can renew her access with the same card.
  h.sql("DELETE FROM raw_hashes");
  assert.equal((await fullFlow(h, alice, serverFixture("a100_80gb_pcie"))).submit!.body.grants_access, true);
});

test("a test of only some GPUs does not give access", async () => {
  const h = new Harness();
  const t = await h.login();
  const doc = serverFixture("container_ecc_hidden");
  doc.gpus = [doc.gpus[0]];
  doc.run.options.gpus = [0];
  const r = (await fullFlow(h, t, doc)).submit!;
  assert.equal(r.body.status, "accepted", JSON.stringify(r.body));
  assert.equal(r.body.grants_access, false);
  assert.match(r.body.reason, /all GPUs/);
});

test("new GitHub accounts and quarantined accounts are flagged; admin review decides", async () => {
  const h = new Harness();
  const t = await h.login(5, "newbie", "2026-10-20T00:00:00Z");
  const r = (await fullFlow(h, t, serverFixture("a100_80gb_pcie"))).submit!;
  assert.equal(r.body.status, "flagged");
  assert.equal(r.body.grants_access, false);
  const admin = h.env.ADMIN_TOKEN as string;
  assert.equal((await h.call("GET", "/v1/admin/flags", undefined, "wrong")).status, 401);
  const flags = await h.call("GET", "/v1/admin/flags", undefined, admin);
  assert.equal(flags.body.flags[0].kind, "submission_flagged");
  const list = await h.call("GET", "/v1/admin/submissions?status=flagged", undefined, admin);
  const id = list.body.submissions[0].id;
  const detail = await h.call("GET", `/v1/admin/submissions/${id}`, undefined, admin);
  assert.ok(detail.body.checks.some((c: any) => c.check_name === "account" && c.result === "flag"));
  const docResp = await h.app.fetch(new Request(`https://registry.test/v1/admin/submissions/${id}/document`,
    { headers: { authorization: `Bearer ${admin}` } }), h.env);
  assert.equal((await docResp.json() as any).kind, "dud.result");
  const ok = await h.call("POST", `/v1/admin/submissions/${id}/decision`, { decision: "accept", note: "known person" }, admin);
  assert.equal(ok.body.grants_access, true);
  assert.equal((await h.call("GET", "/v1/me", undefined, t)).body.account.has_access, true);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'submission_accept'")[0].n, 1);

  // Quarantine: no access, readings hidden from other users.
  await h.call("POST", "/v1/admin/accounts/newbie/quarantine", { note: "test" }, admin);
  assert.equal((await h.call("GET", `/v1/cards/${CARD}`, undefined, t)).status, 403);
  await h.call("POST", "/v1/admin/accounts/newbie/quarantine", { on: false }, admin);
  assert.equal((await h.call("GET", `/v1/cards/${CARD}`, undefined, t)).status, 200);

  // Revoke.
  await h.call("POST", "/v1/admin/accounts/newbie/revoke", { note: "test" }, admin);
  const revoked = await h.call("GET", "/v1/me", undefined, t);
  assert.equal(revoked.status, 401);
  assert.match(revoked.body.message, /stopped your token/);
});

test("a token used from many networks is revoked", async () => {
  const h = new Harness({ SHARE_FLAG_NETWORKS: "2", SHARE_REVOKE_NETWORKS: "4" });
  const t = await h.login();
  for (let i = 0; i < 4; i++) {
    h.network = `asn${i}:US`;
    assert.equal((await h.call("GET", "/v1/me", undefined, t)).status, 200);
  }
  assert.equal(h.sql("SELECT kind FROM admin_flags")[0].kind, "token_sharing_suspected");
  h.network = "asn9:BR";
  assert.equal((await h.call("GET", "/v1/me", undefined, t)).status, 401);
  assert.equal(h.sql("SELECT revoked_reason FROM tokens")[0].revoked_reason, "token_sharing");
});

test("load test required: missing or flat load is rejected, a plausible load passes", async () => {
  for (const [load, expected] of [[null, "rejected"], ["flat", "rejected"], ["ok", "accepted"]] as const) {
    const h = new Harness({ REQUIRE_LOAD: "true" });
    const t = await h.login();
    const doc = serverFixture("a100_80gb_pcie");
    doc.run.options.load_minutes = 2;
    doc.gpus[0].load = null;
    if (load === "ok") doc.gpus[0].load = plausibleLoad(2);
    if (load === "flat") {
      const l = plausibleLoad(2);
      l.series.power_w = l.series.power_w.map(() => 250);
      doc.gpus[0].load = l;
    }
    if (doc.gpus[0].load) {
      // An A100 PCIe: scale the series to its limits.
      const s = doc.gpus[0].load.series;
      s.sm_clock_mhz = s.sm_clock_mhz.map((x: number) => Math.min(x, 1410));
      if (load === "ok") s.power_w = s.power_w.map((x: number) => (x / 700) * 300);
    }
    const r = (await fullFlow(h, t, doc)).submit!;
    assert.equal(r.body.status, expected, `${load}: ${JSON.stringify(r.body)}`);
  }
});

test("stats need enough cards and contributors and return percentiles only", async () => {
  const h = new Harness({ STATS_MIN_CARDS: "20" });
  const t = await h.login();
  await fullFlow(h, t, serverFixture("h100_sxm_healthy"));
  const few = await h.call("GET", "/v1/stats/H100-SXM5-80GB", undefined, t);
  assert.equal(few.body.enough_data, false);
  // Add readings from 12 contributors, 2 cards each.
  for (let c = 0; c < 12; c++) {
    h.sql("INSERT INTO accounts (id, github_id, github_login, created_at, trust) VALUES (?, ?, ?, '2026-01-01', 0.8)", `acc_s${c}`, 1000 + c, `s${c}`);
    for (let k = 0; k < 2; k++) {
      h.sql("INSERT INTO readings (submission_id, card_id, account_id, status, observed_at, model_key, ecc_agg_corr, ecc_agg_unc, remap_corr, remap_unc, " +
        "bank_max, bank_high, bank_partial, bank_low, bank_none, xid_count, gpu_json) VALUES ('s', ?, ?, 'accepted', '2026-10-01', 'H100-SXM5-80GB', ?, 0, 0, 0, 2560, 0, 0, 0, 0, 0, '{}')",
      `card_${c}_${k}`, `acc_s${c}`, c * 10 + k);
    }
  }
  const s = await h.call("GET", "/v1/stats/H100-SXM5-80GB", undefined, t);
  assert.equal(s.body.enough_data, true);
  assert.deepEqual(Object.keys(s.body.percentiles.aggregate_correctable_ecc), ["p10", "p50", "p90"]);
  assert.equal(s.body.percentiles.bank_availability_max_fraction.p50, 1);
  assert.ok(!JSON.stringify(s.body).includes("card_"));
  assert.equal((await h.call("GET", "/v1/stats/NOT-A-MODEL", undefined, t)).status, 404);
});

test("no endpoint lists cards", async () => {
  const h = new Harness();
  const t = await h.login();
  await fullFlow(h, t, serverFixture("a100_80gb_pcie"));
  for (const path of ["/v1/cards", "/v1/cards/", "/v1/readings", "/v1/export", "/v1/stats"])
    assert.equal((await h.call("GET", path, undefined, t)).status, 404, path);
});
