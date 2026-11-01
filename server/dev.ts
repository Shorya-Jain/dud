// Local dev server: the real registry code on your computer, without Cloudflare.
// It uses an in-memory database (empty at each start), a fake GitHub sign-in,
// a very small challenge and it accepts mock-mode results.
//
//   node server/dev.ts            (port 8787)
//   node server/dev.ts 9000       (another port)
//   node server/dev.ts --real     (production challenge and checks: for a real GPU, no mock results)
//
// Then in another terminal:
//   export DUD_API_URL=http://localhost:8787 DUD_TOKEN=<token that this program prints>
//   DUD_MOCK=1 dud full

import { createServer } from "node:http";
import { createApp } from "./src/app.ts";
import { fakeGithub, makeEnv } from "./test/fakes.ts";

const args = process.argv.slice(2);
const real = args.includes("--real");
const port = Number(args.find((a) => a !== "--real") ?? 8787);
const env = makeEnv(real ? { ALLOW_MOCK: "false", REQUIRE_LOAD: "true", CHALLENGE_OVERRIDE: undefined } : {
  ALLOW_MOCK: "true",
  REQUIRE_LOAD: "false",
  CHALLENGE_OVERRIDE: JSON.stringify({ params: { m: 8, n: 8, k: 32, pool: 2, batch: 4 }, count: 16, min_ms: 0, max_ms: 600000, samples_per_gpu: 2 }),
});
const app = createApp({ verifyGithub: fakeGithub, networkOf: () => "dev:local" });

async function devToken(login: string, id: number): Promise<string> {
  const res = await app.fetch(new Request("http://dev/v1/auth/github", {
    method: "POST",
    body: JSON.stringify({ github_token: `gh:${id}:${login}:2015-01-01T00:00:00Z` }),
  }), env);
  return ((await res.json()) as any).token;
}

const server = createServer(async (req, res) => {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  const url = new URL(req.url ?? "/", `http://localhost:${port}`);
  // Dev only: GET /dev/token?login=bob gives a token for a new fake account.
  if (url.pathname === "/dev/token") {
    const login = url.searchParams.get("login") ?? "dev";
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ token: await devToken(login, 10_000 + login.length * 31 + login.charCodeAt(0)) }));
    return;
  }
  const headers = new Headers();
  for (const [k, v] of Object.entries(req.headers)) if (typeof v === "string") headers.set(k, v);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  const response = await app.fetch(new Request(url, { method: req.method, headers, body }), env);
  res.writeHead(response.status, Object.fromEntries(response.headers));
  res.end(Buffer.from(await response.arrayBuffer()));
});

server.listen(port, async () => {
  const token = await devToken("dev", 1);
  console.log(`dud dev registry: http://localhost:${port}${real ? " (real mode: production challenge and checks)" : ""}`);
  console.log(`Token for the account "dev": ${token}`);
  console.log(`Admin token: ${env.ADMIN_TOKEN}`);
  console.log("The database is in memory. It is empty after each start.");
});
