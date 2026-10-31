// Read key values from (redacted) `nvidia-smi -q -x` output.
// The rules copy src/dud/collect/smi_xml.py for the values that the server checks.

import { find, findAll, parseXml, type XmlNode } from "./xml.ts";

export type Val = { ok: boolean; value: any };
const BAD: Val = { ok: false, value: null };
const MARKER = "dud-redacted:";

function raw(el: XmlNode | undefined, path: string): string | null {
  if (!el) return null;
  const node = find(el, path);
  if (node) return node.text.trim();
  const parts = path.split("/");
  for (let i = parts.length - 1; i > 0; i--) {
    const anc = find(el, parts.slice(0, i).join("/"));
    if (anc) return anc.children.length === 0 && anc.text.trim() ? anc.text.trim() : null;
  }
  return null;
}

function isBad(r: string | null): boolean {
  if (r === null) return true;
  const low = r.trim().replace(/^\[|\]$/g, "").trim().toLowerCase();
  return (
    low === "" || low === "n/a" || low === "na" || low.includes("insufficient permission") || low.includes("no permission") ||
    low.includes("not supported") || low.includes("deprecated") || low.includes("error") || low.includes("requires reset")
  );
}

const NUM = /^(-?\d+(?:\.\d+)?)\s*([A-Za-z%()/]*)$/;

function num(el: XmlNode | undefined, path: string, unit?: string, float = false): Val {
  const r = raw(el, path);
  if (isBad(r)) return BAD;
  const m = NUM.exec(r!);
  if (!m || (unit !== undefined && m[2] !== unit)) return BAD;
  const n = parseFloat(m[1]);
  return { ok: true, value: float ? n : Math.trunc(n) };
}

function str(el: XmlNode | undefined, path: string): Val {
  const r = raw(el, path);
  return isBad(r) ? BAD : { ok: true, value: r };
}

function bool(el: XmlNode | undefined, path: string): Val {
  const r = raw(el, path);
  if (isBad(r)) return BAD;
  const low = r!.toLowerCase();
  if (["yes", "enabled", "active"].includes(low)) return { ok: true, value: true };
  if (["no", "disabled", "not active"].includes(low)) return { ok: true, value: false };
  return BAD;
}

function first(el: XmlNode | undefined, ...paths: string[]): string {
  if (el) for (const p of paths) if (find(el, p)) return p;
  return paths[0];
}

function sum(block: XmlNode, tags: string[]): Val {
  if (tags.length === 0) return BAD;
  let total = 0;
  for (const t of tags) {
    const v = num(block, t);
    if (!v.ok) return BAD;
    total += v.value;
  }
  return { ok: true, value: total };
}

function ecc(gpu: XmlNode, tag: string): { correctable: Val; uncorrectable: Val } {
  const block = find(gpu, `ecc_errors/${tag}`);
  if (!block) return { correctable: BAD, uncorrectable: BAD };
  if (find(block, "single_bit")) return { correctable: num(block, "single_bit/total"), uncorrectable: num(block, "double_bit/total") };
  const tags = block.children.map((c) => c.tag);
  return {
    correctable: sum(block, tags.filter((t) => t.endsWith("correctable") && !t.includes("uncorrectable"))),
    uncorrectable: sum(block, tags.filter((t) => t.includes("uncorrectable"))),
  };
}

function cardHash(r: string | null): string | null {
  if (r === null) return null;
  const v = r.trim();
  if (!v.startsWith(MARKER)) return null; // The client must send redacted XML.
  const h = v.slice(v.lastIndexOf(":") + 1);
  return /^[0-9a-f]{64}$/.test(h) ? h : null;
}

export type SmiGpu = {
  bus_id: string;
  uuid_sha256: string | null;
  serial_sha256: string | null;
  raw_uuid_present: boolean; // True if a raw (not redacted) UUID is in the XML.
  values: Record<string, Val>; // Keys are paths inside a GPU entry of the result document.
};

export type SmiDoc = { top: Record<string, Val>; gpus: SmiGpu[] };

export function normBus(bus: string): string {
  const m = /^([0-9a-fA-F]+):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])$/.exec(bus.trim());
  if (!m) return bus.trim().toLowerCase();
  return `${parseInt(m[1], 16).toString(16).padStart(8, "0")}:${m[2].toLowerCase()}:${m[3].toLowerCase()}.${m[4]}`;
}

export function parseSmi(text: string): SmiDoc {
  const root = parseXml(text);
  if (root.tag !== "nvidia_smi_log") throw new Error("root element is not nvidia_smi_log");
  const top = {
    driver_version: str(root, "driver_version"),
    cuda_version: str(root, "cuda_version"),
    timestamp: str(root, "timestamp"),
    attached_gpus: num(root, "attached_gpus"),
  };
  const gpus = findAll(root, "gpu").map((g) => {
    let power = find(g, "gpu_power_readings");
    if (!power) power = find(g, "power_readings");
    const remap = "remapped_rows";
    const vol = ecc(g, "volatile");
    const agg = ecc(g, "aggregate");
    const uuidRaw = raw(g, "uuid");
    const values: Record<string, Val> = {
      "identity.name": str(g, "product_name"),
      "identity.vbios": str(g, "vbios_version"),
      "identity.memory_total_mib": num(g, "fb_memory_usage/total", "MiB"),
      "identity.power_limit_default_w": num(power, "default_power_limit", "W", true),
      "identity.power_limit_current_w": num(power, first(power, "current_power_limit", "enforced_power_limit", "power_limit"), "W", true),
      "identity.power_limit_max_w": num(power, "max_power_limit", "W", true),
      "identity.max_clocks.sm_mhz": num(g, "max_clocks/sm_clock", "MHz"),
      "history.ecc_mode": bool(g, "ecc_mode/current_ecc"),
      "history.ecc.volatile.correctable": vol.correctable,
      "history.ecc.volatile.uncorrectable": vol.uncorrectable,
      "history.ecc.aggregate.correctable": agg.correctable,
      "history.ecc.aggregate.uncorrectable": agg.uncorrectable,
      "history.row_remap.correctable": num(g, `${remap}/remapped_row_corr`),
      "history.row_remap.uncorrectable": num(g, `${remap}/remapped_row_unc`),
      "history.row_remap.pending": bool(g, `${remap}/remapped_row_pending`),
      "history.row_remap.failed": bool(g, `${remap}/remapped_row_failure`),
      "history.retired_pages.correctable": num(g, "retired_pages/multiple_single_bit_retirement/retired_count"),
      "history.retired_pages.uncorrectable": num(g, "retired_pages/double_bit_retirement/retired_count"),
    };
    for (const k of ["max", "high", "partial", "low", "none"])
      values[`history.row_remap.bank_availability.${k}`] = num(g, `${remap}/remapped_row_histogram/row_remap_histogram_${k}`, "bank(s)");
    return {
      bus_id: normBus(g.attrs.id ?? raw(g, "pci/pci_bus_id") ?? ""),
      uuid_sha256: cardHash(uuidRaw),
      serial_sha256: cardHash(raw(g, "serial")),
      raw_uuid_present: uuidRaw !== null && !isBad(uuidRaw) && !uuidRaw.startsWith(MARKER),
      values,
    };
  });
  return { top, gpus };
}

// nvidia-smi writes local time without a zone, for example "Sat Oct 31 12:00:00 2026".
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function smiTimestampMs(text: string, utcOffsetS: number): number | null {
  const m = /^\w{3}\s+(\w{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})\s+(\d{4})$/.exec(text.trim());
  if (!m) return null;
  const month = MONTHS.indexOf(m[1]);
  if (month < 0) return null;
  const local = Date.UTC(+m[6], month, +m[2], +m[3], +m[4], +m[5]);
  return local - utcOffsetS * 1000;
}
