"""Identify the GPU model from the nvidia-smi product name.

The model key links a GPU to its datasheet values in specs.yaml (milestone 2).
The name patterns come from known nvidia-smi output. Check each one against
real output when it is available (see docs/DESIGN.md, "Values to check").
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GpuModel:
    key: str
    form_factor: str
    architecture: str
    # Data center models record ECC errors and row remaps. N/A on these
    # models means that something hides the value.
    has_ecc: bool = True
    has_row_remap: bool = True


_MODELS = [
    (r"H100 80GB HBM3|H100 SXM5 80GB", GpuModel("H100-SXM5-80GB", "SXM", "hopper")),
    (r"H100 PCIe", GpuModel("H100-PCIE-80GB", "PCIe", "hopper")),
    (r"H100 NVL", GpuModel("H100-NVL-94GB", "NVL", "hopper")),
    (r"H200 NVL", GpuModel("H200-NVL-141GB", "NVL", "hopper")),
    (r"H200", GpuModel("H200-SXM-141GB", "SXM", "hopper")),
    (r"A100-SXM4-40GB", GpuModel("A100-SXM4-40GB", "SXM", "ampere")),
    (r"A100-SXM4-80GB", GpuModel("A100-SXM4-80GB", "SXM", "ampere")),
    (r"A100-PCIE-40GB", GpuModel("A100-PCIE-40GB", "PCIe", "ampere")),
    (r"A100 80GB PCIe", GpuModel("A100-PCIE-80GB", "PCIe", "ampere")),
]
_COMPILED = [(re.compile(rf"^(NVIDIA )?({pattern})$", re.I), m) for pattern, m in _MODELS]


def identify(product_name: str | None) -> GpuModel | None:
    if not product_name:
        return None
    for rx, m in _COMPILED:
        if rx.match(product_name.strip()):
            return m
    return None
