// The router. index.ts gives it the real GitHub verifier and clock; tests give fakes.

import { admin } from "./admin.ts";
import { githubVerifier, login, type Ctx, type GithubVerifier } from "./auth.ts";
import { commitChallenge, createChallenge, revealChallenge } from "./challenge.ts";
import { config, realClock, type Clock, type Env } from "./env.ts";
import { ApiError, errorResponse, json, message } from "./http.ts";
import { lookupCard, me, stats } from "./lookup.ts";
import { submit } from "./submit.ts";

export type AppOptions = {
  verifyGithub?: GithubVerifier;
  now?: Clock;
  // Network identity for token-sharing detection. Default: Cloudflare ASN and country.
  networkOf?: (request: Request) => string;
};

function cfNetwork(request: Request): string {
  const cf = (request as any).cf ?? {};
  return `${cf.asn ?? "unknown"}:${cf.country ?? "unknown"}`;
}

export function createApp(options: AppOptions = {}) {
  const verifyGithub = options.verifyGithub ?? githubVerifier;
  const now = options.now ?? realClock;
  const networkOf = options.networkOf ?? cfNetwork;

  async function route(ctx: Ctx): Promise<Response> {
    const url = new URL(ctx.request.url);
    const m = ctx.request.method;
    const parts = url.pathname.split("/").filter(Boolean);
    if (parts[0] !== "v1") throw new ApiError(404, "not_found");
    const [, a, b, c] = parts;

    if (a === "config" && m === "GET")
      return json({ github_client_id: ctx.env.GITHUB_CLIENT_ID, access_days: ctx.cfg.ACCESS_DAYS, schema_version: 1 });
    if (a === "auth" && b === "github" && m === "POST") return login(ctx);
    if (a === "me" && m === "GET") return me(ctx);
    if (a === "challenges" && !b && m === "POST") return createChallenge(ctx);
    if (a === "challenges" && b && c === "commit" && m === "POST") return commitChallenge(ctx, b);
    if (a === "challenges" && b && c === "reveal" && m === "POST") return revealChallenge(ctx, b);
    if (a === "submissions" && !b && m === "POST") return submit(ctx);
    if (a === "cards" && b && !c && m === "GET") return lookupCard(ctx, b);
    if (a === "stats" && b && !c && m === "GET") return stats(ctx, b, url.searchParams.get("provider"));
    if (a === "admin") return admin(ctx, parts.slice(2));
    throw new ApiError(404, "not_found");
  }

  return {
    async fetch(request: Request, env: Env): Promise<Response> {
      const ctx: Ctx = {
        env,
        cfg: config(env),
        now,
        request,
        ip: request.headers.get("cf-connecting-ip") ?? "unknown",
        network: networkOf(request),
        verifyGithub,
      };
      try {
        return await route(ctx);
      } catch (e) {
        if (e instanceof ApiError) return errorResponse(e);
        console.error(e);
        return json({ error: "server_error", message: message("server_error") }, 500);
      }
    },
  };
}
