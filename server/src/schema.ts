// A JSON Schema validator for the subset that result.v1.json uses:
// type, const, enum, required, properties, additionalProperties, items, maxItems,
// minimum, maxLength, pattern, $ref (local), allOf, oneOf, if/then/else.

type Schema = Record<string, any>;

function typeOf(v: unknown): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  if (typeof v === "number") return Number.isInteger(v) ? "integer" : "number";
  return typeof v;
}

// Equality for const and enum. Primitives need no JSON text (the registry runs on the free CPU budget).
function same(a: unknown, b: unknown): boolean {
  if (a === null || typeof a !== "object" || b === null || typeof b !== "object") return a === b;
  return JSON.stringify(a) === JSON.stringify(b);
}

const patterns = new Map<string, RegExp>();
function pattern(p: string): RegExp {
  let r = patterns.get(p);
  if (!r) patterns.set(p, (r = new RegExp(p)));
  return r;
}

// Items schemas that are only a number type: check them in one loop (the load series has thousands).
function plainNumberItems(s: Schema): "number" | "integer" | null {
  const keys = Object.keys(s);
  return keys.length === 1 && (s.type === "number" || s.type === "integer") ? s.type : null;
}

function typeMatches(v: unknown, t: string): boolean {
  const actual = typeOf(v);
  return actual === t || (t === "number" && actual === "integer");
}

// [key, const] pairs if the schema is only properties with a const each, else null. Cached per schema.
const constCache = new WeakMap<Schema, [string, unknown][] | null>();
function constProperties(s: Schema): [string, unknown][] | null {
  if (constCache.has(s)) return constCache.get(s)!;
  let out: [string, unknown][] | null = null;
  if (Object.keys(s).length === 1 && s.properties && typeof s.properties === "object") {
    const entries = Object.entries(s.properties as Record<string, Schema>);
    if (entries.every(([, p]) => Object.keys(p).length === 1 && "const" in p)) out = entries.map(([k, p]) => [k, p.const]);
  }
  constCache.set(s, out);
  return out;
}

export function validate(root: Schema, value: unknown, maxErrors = 10): string[] {
  const errors: string[] = [];

  function resolve(ref: string): Schema {
    if (!ref.startsWith("#/")) throw new Error(`unsupported $ref ${ref}`);
    return ref.slice(2).split("/").reduce((s: any, k) => s[k], root);
  }

  function check(s: Schema, v: any, path: string): boolean {
    const before = errors.length;
    if (s.$ref) check(resolve(s.$ref), v, path);
    if ("const" in s && !same(v, s.const)) errors.push(`${path}: must be ${JSON.stringify(s.const)}`);
    if (s.enum && !s.enum.some((e: unknown) => same(e, v))) errors.push(`${path}: not an allowed value`);
    if (s.type) {
      const okType = typeof s.type === "string" ? typeMatches(v, s.type) : s.type.some((t: string) => typeMatches(v, t));
      if (!okType) {
        errors.push(`${path}: must be ${[].concat(s.type).join(" or ")}`);
        return false;
      }
    }
    if (typeof v === "number" && s.minimum !== undefined && v < s.minimum) errors.push(`${path}: below ${s.minimum}`);
    if (typeof v === "string") {
      if (s.maxLength !== undefined && v.length > s.maxLength) errors.push(`${path}: longer than ${s.maxLength}`);
      if (s.pattern && !pattern(s.pattern).test(v)) errors.push(`${path}: does not match the pattern`);
    }
    if (Array.isArray(v)) {
      if (s.maxItems !== undefined && v.length > s.maxItems) errors.push(`${path}: more than ${s.maxItems} items`);
      const plain = s.items ? plainNumberItems(s.items) : null;
      if (plain) {
        const bad = v.findIndex((x) => typeof x !== "number" || (plain === "integer" && !Number.isInteger(x)));
        if (bad >= 0) errors.push(`${path}[${bad}]: must be ${plain}`);
      } else if (s.items) v.forEach((item, i) => check(s.items, item, `${path}[${i}]`));
    }
    if (typeOf(v) === "object") {
      for (const key of s.required ?? []) if (!(key in v)) errors.push(`${path}: missing ${key}`);
      const props = s.properties ?? {};
      for (const key in v) {
        const item = v[key];
        if (key in props) check(props[key], item, `${path}.${key}`);
        else if (s.additionalProperties === false) errors.push(`${path}: unknown key ${key}`);
        else if (typeof s.additionalProperties === "object") check(s.additionalProperties, item, `${path}.${key}`);
      }
    }
    for (const sub of s.allOf ?? []) check(sub, v, path);
    if (s.oneOf) {
      const passing = s.oneOf.filter((sub: Schema) => quiet(sub, v));
      if (passing.length !== 1) errors.push(`${path}: must match exactly one option`);
    }
    if (s.if) {
      const branch = quiet(s.if, v) ? s.then : s.else;
      if (branch) check(branch, v, path);
    }
    return errors.length === before;
  }

  // Check without recording errors.
  function quiet(s: Schema, v: unknown): boolean {
    // Fast path for {properties: {key: {const: x}}} (the "if" of every field).
    const consts = constProperties(s);
    if (consts) return typeOf(v) !== "object" || consts.every(([k, c]) => !(k in (v as any)) || same((v as any)[k], c));
    const saved = errors.length;
    const ok = check(s, v, "");
    errors.length = saved;
    return ok;
  }

  check(root, value, "$");
  return errors.slice(0, maxErrors);
}
