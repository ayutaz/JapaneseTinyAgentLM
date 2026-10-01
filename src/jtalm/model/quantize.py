# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Weight quantization for the Action LM (M5): fake-quantized checkpoints and artifact sizes.

    uv run --group train python -m jtalm.model.quantize --ckpt runs/.../3m/best.pt --bits 8 4

Every 2-D weight (attention, MLP, and the tied embedding / output head) is quantized per row in
groups of ``--group`` values with a symmetric scale (round-to-nearest), then dequantized back to
float. The result is saved next to the input as ``best_q8_g64.pt`` etc., so ``jtalm.model.evaluate``
scores it unchanged. RMSNorm weights stay in float. Sizes assume one fp16 scale per group, the
layout planned for the ESP32 runtime (docs/architecture.md).
"""

import argparse
import json
from pathlib import Path
from typing import Any

import torch

from jtalm.model.evaluate import load_model


def quantize_tensor(w: torch.Tensor, bits: int, group: int) -> torch.Tensor:
    """Symmetric per-group round-to-nearest along the last dim; returns dequantized weights."""
    rows, cols = w.shape
    if cols % group:
        raise ValueError(f"last dimension {cols} is not a multiple of group {group}")
    qmax = 2 ** (bits - 1) - 1
    g = w.float().reshape(rows, cols // group, group)
    scale = g.abs().amax(dim=-1, keepdim=True).clamp(min=1e-12) / qmax
    q = torch.clamp(torch.round(g / scale), -qmax - 1, qmax)
    return (q * scale).reshape(rows, cols).to(w.dtype)


def quantize_state(
    state: dict[str, torch.Tensor], bits: int, group: int
) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    out, n_quant, n_float, max_err = {}, 0, 0, 0.0
    for name, w in state.items():
        if w.dim() == 2:
            qw = quantize_tensor(w, bits, group)
            max_err = max(max_err, float((qw - w).abs().max()))
            out[name] = qw
            n_quant += w.numel()
        else:
            out[name] = w
            n_float += w.numel()
    size = n_quant * bits / 8 + (n_quant // group) * 2 + n_float * 4
    info = {
        "bits": bits,
        "group": group,
        "quantized_params": n_quant,
        "float_params": n_float,
        "artifact_bytes_estimate": int(size),
        "max_abs_error": max_err,
    }
    return out, info


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ckpt", type=Path, nargs="+", required=True)
    parser.add_argument("--bits", type=int, nargs="+", default=[8, 4])
    parser.add_argument("--group", type=int, default=64)
    args = parser.parse_args(argv)

    report = {}
    for ckpt in args.ckpt:
        _, state = load_model(ckpt, torch.device("cpu"))
        fp_params = sum(v.numel() for v in state["state_dict"].values())
        report[str(ckpt)] = {"fp32_bytes": fp_params * 4}
        for bits in args.bits:
            q_state, info = quantize_state(state["state_dict"], bits, args.group)
            out = ckpt.with_name(f"{ckpt.stem}_q{bits}_g{args.group}.pt")
            torch.save({**state, "state_dict": q_state, "quantization": info}, out)
            report[str(ckpt)][f"int{bits}"] = {**info, "file": out.name}
            print(
                f"{out}: {info['artifact_bytes_estimate'] / 1e6:.2f} MB (int{bits}, g{args.group})"
            )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
