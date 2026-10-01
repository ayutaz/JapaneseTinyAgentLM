# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Print a JSON summary proving torch can use the GPU (run with ``uv run --group train``)."""

import json
import time

import torch


def main() -> None:
    info: dict = {"torch": torch.__version__, "cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        info["device"] = torch.cuda.get_device_name(0)
        info["cuda_runtime"] = torch.version.cuda
        x = torch.randn(4096, 4096, device="cuda")
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(10):
            y = x @ x
        torch.cuda.synchronize()
        sec = time.perf_counter() - t0
        info["matmul_tflops"] = round(10 * 2 * 4096**3 / sec / 1e12, 2)
        info["checksum_finite"] = bool(torch.isfinite(y).all())
    print(json.dumps(info))


if __name__ == "__main__":
    main()
