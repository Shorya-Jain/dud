// A small XML parser for nvidia-smi output. Workers have no DOMParser.
// Handles elements, attributes, text, entities, comments, <?...?> and <!DOCTYPE>.
// Limits size and depth, because the input comes from an untrusted client.

export type XmlNode = { tag: string; attrs: Record<string, string>; children: XmlNode[]; text: string };

const ENTITIES: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

function decode(s: string): string {
  return s.replace(/&(#x[0-9a-fA-F]+|#\d+|[a-z]+);/g, (m, e: string) => {
    if (e[0] === "#") return String.fromCodePoint(e[1] === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENTITIES[e] ?? m;
  });
}

export class XmlError extends Error {}

export function parseXml(src: string, maxDepth = 32, maxNodes = 200_000): XmlNode {
  const root: XmlNode = { tag: "#root", attrs: {}, children: [], text: "" };
  const stack: XmlNode[] = [root];
  let i = 0;
  let nodes = 0;
  while (i < src.length) {
    const lt = src.indexOf("<", i);
    if (lt < 0) {
      stack[stack.length - 1].text += decode(src.slice(i));
      break;
    }
    if (lt > i) stack[stack.length - 1].text += decode(src.slice(i, lt));
    if (src.startsWith("<!--", lt)) {
      const end = src.indexOf("-->", lt);
      if (end < 0) throw new XmlError("comment does not end");
      i = end + 3;
    } else if (src.startsWith("<?", lt)) {
      const end = src.indexOf("?>", lt);
      if (end < 0) throw new XmlError("declaration does not end");
      i = end + 2;
    } else if (src.startsWith("<!", lt)) {
      const end = src.indexOf(">", lt);
      if (end < 0) throw new XmlError("doctype does not end");
      i = end + 1;
    } else if (src[lt + 1] === "/") {
      const end = src.indexOf(">", lt);
      if (end < 0) throw new XmlError("end tag does not end");
      const tag = src.slice(lt + 2, end).trim();
      const top = stack.pop();
      if (!top || top.tag !== tag || stack.length === 0) throw new XmlError(`unexpected </${tag}>`);
      i = end + 1;
    } else {
      const end = src.indexOf(">", lt);
      if (end < 0) throw new XmlError("start tag does not end");
      let body = src.slice(lt + 1, end);
      const selfClosing = body.endsWith("/");
      if (selfClosing) body = body.slice(0, -1);
      const m = /^([A-Za-z_][\w.\-:]*)([\s\S]*)$/.exec(body.trim());
      if (!m) throw new XmlError("bad start tag");
      const attrs: Record<string, string> = {};
      const re = /([A-Za-z_][\w.\-:]*)\s*=\s*("([^"]*)"|'([^']*)')/g;
      let a: RegExpExecArray | null;
      while ((a = re.exec(m[2])) !== null) attrs[a[1]] = decode(a[3] ?? a[4] ?? "");
      const node: XmlNode = { tag: m[1], attrs, children: [], text: "" };
      if (++nodes > maxNodes) throw new XmlError("too many elements");
      stack[stack.length - 1].children.push(node);
      if (!selfClosing) {
        stack.push(node);
        if (stack.length > maxDepth) throw new XmlError("too deep");
      }
      i = end + 1;
    }
  }
  if (stack.length !== 1) throw new XmlError(`<${stack[stack.length - 1].tag}> does not end`);
  if (root.children.length !== 1) throw new XmlError("need exactly one root element");
  return root.children[0];
}

export function find(node: XmlNode | undefined, path: string): XmlNode | undefined {
  let cur = node;
  for (const part of path.split("/")) {
    if (!cur) return undefined;
    cur = cur.children.find((c) => c.tag === part);
  }
  return cur;
}

export function findAll(node: XmlNode, tag: string): XmlNode[] {
  return node.children.filter((c) => c.tag === tag);
}
