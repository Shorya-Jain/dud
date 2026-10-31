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

function typeMatches(v: unknown, t: string): boolean {
  const actual = typeOf(v);
  return actual === t || (t === "number" && actual === "integer");
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
    if ("const" in s && JSON.stringify(v) !== JSON.stringify(s.const)) errors.push(`${path}: must be ${JSON.stringify(s.const)}`);
    if (s.enum && !s.enum.some((e: unknown) => JSON.stringify(e) === JSON.stringify(v))) errors.push(`${path}: not an allowed value`);
    if (s.type) {
      const types: string[] = Array.isArray(s.type) ? s.type : [s.type];
      if (!types.some((t) => typeMatches(v, t))) {
        errors.push(`${path}: must be ${types.join(" or ")}`);
        return false;
      }
    }
    if (typeof v === "number" && s.minimum !== undefined && v < s.minimum) errors.push(`${path}: below ${s.minimum}`);
    if (typeof v === "string") {
      if (s.maxLength !== undefined && v.length > s.maxLength) errors.push(`${path}: longer than ${s.maxLength}`);
      if (s.pattern && !new RegExp(s.pattern).test(v)) errors.push(`${path}: does not match the pattern`);
    }
    if (Array.isArray(v)) {
      if (s.maxItems !== undefined && v.length > s.maxItems) errors.push(`${path}: more than ${s.maxItems} items`);
      if (s.items) v.forEach((item, i) => check(s.items, item, `${path}[${i}]`));
    }
    if (typeOf(v) === "object") {
      for (const key of s.required ?? []) if (!(key in v)) errors.push(`${path}: missing ${key}`);
      const props = s.properties ?? {};
      for (const [key, item] of Object.entries(v)) {
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
    const saved = errors.length;
    const ok = check(s, v, "");
    errors.length = saved;
    return ok;
  }

  check(root, value, "$");
  return errors.slice(0, maxErrors);
}
