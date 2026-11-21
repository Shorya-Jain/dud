import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { canonical, chainOf, leafOf, ZERO } from "../src/log.ts";
import { fullFlow, Harness, serverFixture } from "./fakes.ts";

const sha = (s: string) => createHash("sha256").update(s).digest("hex");

// The same values are in tests/test_translog.py. The client and the server must agree.
const VECTOR_ENTRIES = ['{"v":1,"type":"reading","fp":"aa"}', '{"v":1,"type":"account","account":"bb","status":"quarantined"}'];
const VECTOR_CHAIN = "d16a8c495fb37e293f1de54b679e23db8d80600a7e4cdf4f5f0dd81505e67484";

test("log hashes match the shared vector", async () => {
  let chain = ZERO;
  for (const e of VECTOR_ENTRIES) chain = await chainOf(chain, await leafOf(e));
  assert.equal(chain, VECTOR_CHAIN);
  assert.equal(canonical({ b: [1, { d: null, c: true }], a: "x" }), '{"a":"x","b":[1,{"c":true,"d":null}]}');
});

async function checkChain(entries: any[]) {
  let chain = ZERO;
  for (const e of entries) {
    assert.equal(e.leaf, await leafOf(e.entry));
    chain = await chainOf(chain, e.leaf);
    assert.equal(e.chain, chain);
  }
  return chain;
}

test("accepted readings go into the log, and lookups prove them", async () => {
  const h = new Harness();
  const t = await h.login();
  const doc = serverFixture("a100_80gb_pcie");
  const r = (await fullFlow(h, t, doc)).submit!;
  assert.equal(r.body.status, "accepted");
  assert.equal(r.body.receipts.length, 1);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM log_pending")[0].n, 1);
  const admin = h.env.ADMIN_TOKEN as string;
  assert.equal((await h.call("POST", "/v1/admin/log/run", {}, admin)).status, 200);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM log_pending")[0].n, 0);

  // Public heads: a day and a chain value. No sequence numbers, no counts.
  const pub = await h.call("GET", "/v1/log/heads");
  assert.equal(pub.status, 200);
  assert.deepEqual(Object.keys(pub.body.heads[0]).sort(), ["chain", "day"]);

  // The entries need access.
  assert.equal((await h.call("GET", "/v1/log")).status, 401);
  const page = await h.call("GET", "/v1/log?after=0", undefined, t);
  assert.equal(page.status, 200);
  assert.equal(page.body.entries.length, 1);
  const head = await checkChain(page.body.entries);
  assert.equal(page.body.heads[0].chain, head);
  assert.equal(pub.body.heads[0].chain, head);

  // The lookup gives the proof: canonical text, fingerprint and sequence number.
  const card = doc.gpus[0].card.uuid_sha256.value;
  const look = await h.call("GET", `/v1/cards/${card}`, undefined, t);
  const reading = look.body.readings[0];
  const { trust, yours, log, ...shown } = reading;
  assert.equal(log.seq, 1);
  assert.equal(log.fp, r.body.receipts[0].fp);
  assert.equal(log.fp, sha(`dud-log-v1:reading:${card}:${log.canonical}`));
  assert.deepEqual(JSON.parse(log.canonical), shown);
  assert.equal(JSON.parse(page.body.entries[0].entry).fp, log.fp);

  // A change to a stored reading shows: the row no longer matches its logged canonical text.
  h.sql("UPDATE readings SET ecc_agg_unc = 999");
  const changed = (await h.call("GET", `/v1/cards/${card}`, undefined, t)).body.readings[0];
  const { trust: _t, yours: _y, log: l2, ...shown2 } = changed;
  assert.notDeepEqual(JSON.parse(l2.canonical), shown2);
});

test("quarantine and admin acceptance go into the log; heads are one per day", async () => {
  const h = new Harness();
  const t = await h.login(5, "newbie", "2026-10-20T00:00:00Z");
  const r = (await fullFlow(h, t, serverFixture("a100_80gb_pcie"))).submit!;
  assert.equal(r.body.status, "flagged");
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM log_pending")[0].n, 0); // Not visible yet: not in the log.
  const admin = h.env.ADMIN_TOKEN as string;
  const id = (await h.call("GET", "/v1/admin/submissions?status=flagged", undefined, admin)).body.submissions[0].id;
  await h.call("POST", `/v1/admin/submissions/${id}/decision`, { decision: "accept", note: "ok" }, admin);
  await h.call("POST", "/v1/admin/accounts/newbie/quarantine", { note: "test" }, admin);
  await h.call("POST", "/v1/admin/log/run", {}, admin);
  const entries = h.sql("SELECT entry_json FROM log ORDER BY seq").map((x: any) => JSON.parse(x.entry_json));
  assert.deepEqual(entries.map((e: any) => e.type), ["reading", "account"]);
  assert.equal(entries[1].status, "quarantined");
  assert.ok(!JSON.stringify(entries).includes("newbie"));

  // Same day: the head does not change. Next day: a new head.
  await h.call("POST", "/v1/admin/accounts/newbie/quarantine", { on: false }, admin);
  await h.call("POST", "/v1/admin/log/run", {}, admin);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM log_heads")[0].n, 1);
  h.t += 86_400_000;
  await h.call("POST", "/v1/admin/log/run", {}, admin);
  const heads = h.sql("SELECT seq FROM log_heads ORDER BY day").map((x: any) => x.seq);
  assert.deepEqual(heads, [2, 3]);
});

test("the cron handler runs the log", async () => {
  const h = new Harness();
  const t = await h.login();
  await fullFlow(h, t, serverFixture("a100_80gb_pcie"));
  await (h.app as any).scheduled({}, h.env);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM log")[0].n, 1);
  assert.equal(h.sql("SELECT COUNT(*) AS n FROM log_heads")[0].n, 1);
});
