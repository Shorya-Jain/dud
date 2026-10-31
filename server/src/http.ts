// JSON responses and error messages. Messages are in Simplified Technical English
// (see docs/GLOSSARY.md). The CLI shows `message` to the user as it is.

export const MESSAGES = {
  bad_request: "The request is not correct. {detail}",
  not_found: "The registry does not have this item.",
  unauthorized: "Your token is not valid. Run dud login.",
  revoked: "The registry stopped your token. Run dud login to get a new token. If this occurs again, speak to the registry owner.",
  no_access: "You do not have registry access. Run dud full and send the result. An accepted full test gives {days} days of access.",
  quota: "You used all {quota} lookups for today. Try again after 00:00 UTC.",
  rate_limited: "You sent too many requests of this type today. Try again tomorrow.",
  github_failed: "GitHub did not accept the sign-in. Run dud login again.",
  challenge_invalid: "This challenge is not valid or it expired. Start a new full test.",
  challenge_state: "This challenge is not ready for this step. Start a new full test.",
  challenge_failed: "The challenge check failed: {detail}. Start a new full test.",
  too_large: "The result file is too large. The maximum size is {mb} MB.",
  admin_only: "This request needs the admin token.",
  server_error: "The registry has a problem. Try again later.",
};

export type MessageKey = keyof typeof MESSAGES;

export class ApiError extends Error {
  status: number;
  code: MessageKey;
  values: Record<string, string | number>;
  constructor(status: number, code: MessageKey, values: Record<string, string | number> = {}) {
    super(code);
    this.status = status;
    this.code = code;
    this.values = values;
  }
}

export function message(code: MessageKey, values: Record<string, string | number> = {}): string {
  return MESSAGES[code].replace(/\{(\w+)\}/g, (_, k) => String(values[k] ?? "")).trim();
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

export function errorResponse(e: ApiError): Response {
  return json({ error: e.code, message: message(e.code, e.values) }, e.status);
}

export async function readJson(request: Request, maxBytes: number): Promise<any> {
  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > maxBytes) throw new ApiError(413, "too_large", { mb: Math.round(maxBytes / 1e6) });
  const text = await request.text();
  if (text.length > maxBytes) throw new ApiError(413, "too_large", { mb: Math.round(maxBytes / 1e6) });
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError(400, "bad_request", { detail: "The body is not JSON." });
  }
}
