# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Package the Action LM for Hugging Face, run the packaged model, and publish it.

    uv run --group train python -m jtalm.model.release prepare \
        --ckpt <best.pt> --ckpt-q4 <best_q4_g64.pt> --jtlm <3m_q4_g64.jtlm> \
        --suite runs/local/suite_v051_3m_q4 --gate 0.86808 --out runs/release/action_3m
    uv run --group train python -m jtalm.model.release run runs/release/action_3m 右を向いて
    uv run python -m jtalm.model.release publish runs/release/action_3m --confirm

``prepare`` writes everything the model repository holds: the INT4 weights as evaluated (stored
dequantized in fp32 safetensors, identical to what the ESP32 computes), the fp32 weights before
quantization, the tokenizer, the Action schema, the ``.jtlm`` file for the firmware, the
evaluation tables and the model card. ``publish`` creates the repository as private, uploads,
turns off Community contributions and only then makes it public. It requires ``--confirm``: a
model is published only after the user has reviewed the prepared folder.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file, save_file

from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.data import Codec
from jtalm.model.decode import greedy
from jtalm.model.grammar import ActionGrammar
from jtalm.model.transformer import ActionLM, ModelConfig

REPO_ID = "ayousanz/JapaneseTinyAgentLM-Action-3M"
CARD_TEMPLATE = Path(__file__).with_name("model_card_action.md")
SCHEMA = PROJECT_ROOT / "src/jtalm/action/action_schema_v0.json"
JTLM_NAME = "jtalm_action_3m_q4_g64.jtlm"
FIRMWARE_NAME = "stackchan_k151_jtalm_action.bin"
FIRMWARE_DIR = PROJECT_ROOT / "firmware/jtalm_action"
# Flash layout of firmware/jtalm_action (partitions.csv); the model partition starts at 0x200000.
FLASH_LAYOUT = (
    (0x0, "bootloader/bootloader.bin"),
    (0x8000, "partition_table/partition-table.bin"),
    (0x10000, "jtalm_action.bin"),
)
MODEL_OFFSET = 0x200000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save_weights(ckpt: Path, out: Path) -> dict[str, Any]:
    state = torch.load(ckpt, map_location="cpu", weights_only=False)
    tensors = {k: v.contiguous().float() for k, v in state["state_dict"].items()}
    save_file(tensors, out, metadata={"format": "pt"})
    return state


def merge_firmware(build: Path, jtlm: Path, out: Path) -> None:
    """One image to write at 0x0: bootloader, partition table, app and model, gaps filled 0xFF.

    Same bytes as ``esptool merge-bin`` with the flash settings already in the bootloader header.
    """
    image = bytearray()
    for offset, data in [*((o, (build / f).read_bytes()) for o, f in FLASH_LAYOUT),
                         (MODEL_OFFSET, jtlm.read_bytes())]:  # fmt: skip
        if len(image) > offset:
            raise SystemExit(f"firmware part overlaps 0x{offset:x}")
        image += bytes([0xFF]) * (offset - len(image)) + data
    out.write_bytes(bytes(image))


def prepare(args: argparse.Namespace) -> Path:
    out: Path = args.out
    if out.exists():
        shutil.rmtree(out)
    (out / "eval").mkdir(parents=True)
    state = _save_weights(args.ckpt_q4, out / "model.safetensors")
    _save_weights(args.ckpt, out / "model_fp32.safetensors")
    codec = Codec(args.tokenizer)
    if state["tokenizer_sha256"] != codec.sha256:
        raise SystemExit("tokenizer sha256 mismatch")
    shutil.copy(args.tokenizer, out / "tokenizer.model")
    shutil.copy(SCHEMA, out / "action_schema_v0.json")
    shutil.copy(args.jtlm, out / JTLM_NAME)
    shutil.copy(Path(__file__).with_name("hf_inference.py"), out / "inference.py")
    fw = out / "firmware"
    fw.mkdir()
    merge_firmware(args.firmware_build, args.jtlm, fw / FIRMWARE_NAME)
    shutil.copy(PROJECT_ROOT / "firmware/tools/stackchan_chat.py", fw / "stackchan_chat.py")
    shutil.copytree(FIRMWARE_DIR / "licenses", fw / "licenses")
    config = {
        "architecture": "ActionLM (decoder-only Transformer: RMSNorm, RoPE, GQA, SwiGLU, tied "
        "embeddings)",
        **state["config"],
        "dropout": 0.0,
        "tokenizer": "tokenizer.model",
        "tokenizer_sha256": codec.sha256,
        "schema": "action_schema_v0.json",
        "quantization": {"bits": 4, "group": 64, "scale_dtype": "float16"},
        "gate_threshold": args.gate,
        "training_data": args.data_version,
        "train_seed": state["args"]["seed"],
    }
    (out / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    for name in ("suite.md", "suite.json"):
        shutil.copy(args.suite / name, out / "eval" / name)
    for extra in args.eval_extra:
        shutil.copy(extra, out / "eval" / extra.name)

    params = sum(t.numel() for t in load_file(out / "model.safetensors").values())
    values = {
        "PARAMS": f"{params:,}",
        "GATE": f"{args.gate}",
        "JTLM": JTLM_NAME,
        "JTLM_BYTES": f"{(out / JTLM_NAME).stat().st_size:,}",
        "JTLM_SHA256": _sha256(out / JTLM_NAME),
        "FIRMWARE": f"firmware/{FIRMWARE_NAME}",
        "FIRMWARE_BYTES": f"{(fw / FIRMWARE_NAME).stat().st_size:,}",
        "APP_SHA256": _sha256(args.firmware_build / "jtalm_action.bin"),
        "SUITE": (args.suite / "suite.md").read_text(encoding="utf-8").strip(),
        "EXTRA": "\n\n".join(p.read_text(encoding="utf-8").strip() for p in args.eval_extra),
    }
    card = CARD_TEMPLATE.read_text(encoding="utf-8")
    for key, value in values.items():
        card = card.replace("{{" + key + "}}", value)
    if "{{" in card:
        raise SystemExit("unfilled placeholder in the model card")
    (out / "README.md").write_text(card, encoding="utf-8")
    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    for p in files:  # LF everywhere, so `sha256sum -c` works on Linux after a Windows build
        if p.suffix in (".md", ".json", ".py", ".txt", ".rst"):
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n"))
    sums = [f"{_sha256(p)}  {p.relative_to(out).as_posix()}" for p in files]
    (out / "SHA256SUMS").write_bytes(("\n".join(sums) + "\n").encode())
    return out


def load_released(folder: Path, device: str = "cpu") -> tuple[ActionLM, Codec, dict[str, Any]]:
    """Load a prepared (or downloaded) model folder."""
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    fields = ModelConfig.__dataclass_fields__
    model = ActionLM(ModelConfig(**{k: v for k, v in config.items() if k in fields}))
    model.load_state_dict(load_file(folder / "model.safetensors"))
    return model.to(device).eval(), Codec(folder / config["tokenizer"]), config


def run(folder: Path, prompts: list[str]) -> list[dict[str, Any]]:
    model, codec, config = load_released(folder)
    preds = greedy(model, codec, prompts, grammar=ActionGrammar(codec))
    gate = config["gate_threshold"]
    return [
        {
            "input": text,
            "output": json.loads("[]" if p.min_prob < gate else p.text),
            "confidence": round(p.min_prob, 4),
        }
        for text, p in zip(prompts, preds, strict=True)
    ]


def publish(folder: Path, repo_id: str) -> str:
    from huggingface_hub import HfApi

    from jtalm.infra.env import read_secret
    from jtalm.infra.hf import community_disabled, disable_community

    api = HfApi(token=read_secret("HF_TOKEN"))
    api.create_repo(repo_id, repo_type="model", private=True, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="model",
        folder_path=folder,
        commit_message="Add JapaneseTinyAgentLM Action LM 3M",
    )
    disable_community(api, repo_id, "model")  # before it becomes public
    api.update_repo_settings(repo_id, repo_type="model", private=False)
    info = api.model_info(repo_id)
    community = "off" if community_disabled(api, repo_id, "model") else "ON"
    return f"https://huggingface.co/{repo_id} (private={info.private}, community={community})"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--ckpt", type=Path, required=True, help="fp32 best.pt")
    p.add_argument("--ckpt-q4", type=Path, required=True, help="best_q4_g64.pt (as evaluated)")
    p.add_argument("--jtlm", type=Path, required=True)
    p.add_argument("--suite", type=Path, required=True, help="eval_suite output of --ckpt-q4")
    p.add_argument("--gate", type=float, required=True)
    p.add_argument(
        "--tokenizer", type=Path, default=PROJECT_ROOT / "tokenizer/out/action_v0_sp2048.model"
    )
    p.add_argument("--data-version", default="action v0.5.1")
    p.add_argument(
        "--firmware-build", type=Path, default=FIRMWARE_DIR / "build_release",
        help="ESP-IDF build directory of firmware/jtalm_action",
    )  # fmt: skip
    p.add_argument("--eval-extra", type=Path, nargs="*", default=[], help="more eval tables (.md)")
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "runs/release/action_3m")
    r = sub.add_parser("run")
    r.add_argument("folder", type=Path)
    r.add_argument("prompts", nargs="+")
    u = sub.add_parser("publish")
    u.add_argument("folder", type=Path)
    u.add_argument("--repo", default=REPO_ID)
    u.add_argument("--confirm", action="store_true", help="required: publishing is public")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.cmd == "prepare":
        print(prepare(args))
    elif args.cmd == "run":
        for row in run(args.folder, args.prompts):
            print(json.dumps(row, ensure_ascii=False))
    elif not args.confirm:
        parser.error("publishing is public; pass --confirm after the user reviewed the folder")
    else:
        print(publish(args.folder, args.repo))


if __name__ == "__main__":
    main()
