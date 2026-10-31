// Product name -> model key. Copy of src/dud/gpumodels.py. test/models.test.ts keeps them the same.

const MODELS: [string, string][] = [
  ["H100 80GB HBM3|H100 SXM5 80GB", "H100-SXM5-80GB"],
  ["H100 PCIe", "H100-PCIE-80GB"],
  ["H100 NVL", "H100-NVL-94GB"],
  ["H200 NVL", "H200-NVL-141GB"],
  ["H200", "H200-SXM-141GB"],
  ["A100-SXM4-40GB", "A100-SXM4-40GB"],
  ["A100-SXM4-80GB", "A100-SXM4-80GB"],
  ["A100-PCIE-40GB", "A100-PCIE-40GB"],
  ["A100 80GB PCIe", "A100-PCIE-80GB"],
];
const COMPILED = MODELS.map(([p, key]) => [new RegExp(`^(NVIDIA )?(${p})$`, "i"), key] as const);

export function identify(name: string | null | undefined): string | null {
  if (!name) return null;
  for (const [rx, key] of COMPILED) if (rx.test(name.trim())) return key;
  return null;
}
