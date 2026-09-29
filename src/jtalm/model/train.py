"""Train an Action LM from scratch (M4).

    uv run --group train python -m jtalm.model.train --size 5m \
        --tokenizer tokenizer/out/action_v0_sp2048.model --out runs/local/5m

The checkpoint with the best validation exact match (greedy) is kept as ``best.pt``; ties go to
the lower validation loss. The evaluation set is never read here.
"""

import argparse
import json
import math
import random
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from jtalm.eval.cases import load_cases
from jtalm.eval.metrics import evaluate
from jtalm.infra.env import PROJECT_ROOT
from jtalm.model.data import IGNORE, Codec, batches, collate, encode_cases
from jtalm.model.decode import greedy
from jtalm.model.transformer import SIZES, ActionLM, count_params, make_config


def pick_device(name: str) -> torch.device:
    if name == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.device(name)


def lr_at(step: int, total: int, peak: float, warmup: int, min_ratio: float) -> float:
    if step < warmup:
        return peak * (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return peak * (min_ratio + (1 - min_ratio) * 0.5 * (1 + math.cos(math.pi * progress)))


def make_optimizer(model: ActionLM, lr: float, weight_decay: float) -> torch.optim.AdamW:
    decay = [p for p in model.parameters() if p.dim() >= 2]
    no_decay = [p for p in model.parameters() if p.dim() < 2]
    groups = [
        {"params": decay, "weight_decay": weight_decay},
        {"params": no_decay, "weight_decay": 0.0},
    ]
    return torch.optim.AdamW(groups, lr=lr, betas=(0.9, 0.95), eps=1e-8)


def loss_fn(model: ActionLM, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    logits = model(x)
    return F.cross_entropy(logits.flatten(0, 1).float(), y.flatten(), ignore_index=IGNORE)


@torch.no_grad()
def val_loss(model: ActionLM, examples: list, device: torch.device, pad: int) -> float:
    model.eval()
    total, count = 0.0, 0
    for i in range(0, len(examples), 256):
        x, y = collate(examples[i : i + 256], pad)
        x, y = x.to(device), y.to(device)
        n = int((y != IGNORE).sum())
        total += float(loss_fn(model, x, y)) * n
        count += n
    model.train()
    return total / count


def save(path: Path, model: ActionLM, codec: Codec, meta: dict[str, Any]) -> None:
    state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    torch.save(
        {
            "config": model.cfg.to_dict(),
            "state_dict": state,
            "tokenizer_sha256": codec.sha256,
            **meta,
        },
        path,
    )


def train(args: argparse.Namespace) -> dict[str, Any]:
    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    device = pick_device(args.device)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    codec = Codec(args.tokenizer)
    train_cases = load_cases(Path(args.data) / "train.jsonl")
    val_cases = load_cases(Path(args.data) / "val.jsonl")
    train_ex = encode_cases(codec, train_cases)
    val_ex = encode_cases(codec, val_cases)

    cfg = make_config(args.size, codec.vocab_size, dropout=args.dropout)
    model = ActionLM(cfg).to(device)
    n_params = count_params(model)
    steps_per_epoch = math.ceil(len(train_ex) / args.batch_size)
    total_steps = args.max_steps or steps_per_epoch * args.epochs
    opt = make_optimizer(model, args.lr, args.weight_decay)
    use_bf16 = device.type == "cuda"
    print(f"{args.size}: {n_params:,} params, {total_steps} steps on {device}")

    log_path = out / "log.jsonl"
    log_path.write_text("", encoding="utf-8")
    best: dict[str, Any] = {"val_exact": -1.0, "val_loss": math.inf, "epoch": 0}
    step, t0 = 0, time.monotonic()
    epoch = 0
    while step < total_steps:
        epoch += 1
        model.train()
        train_sum, train_n = 0.0, 0
        for batch in batches(train_ex, args.batch_size, rng):
            if step >= total_steps:
                break
            for g in opt.param_groups:
                g["lr"] = lr_at(step, total_steps, args.lr, args.warmup, args.min_lr_ratio)
            x, y = collate(batch, codec.pad)
            x, y = x.to(device), y.to(device)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
                loss = loss_fn(model, x, y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_sum += float(loss.detach()) * len(batch)
            train_n += len(batch)
            step += 1

        if epoch % args.eval_every and step < total_steps:
            continue
        vl = val_loss(model, val_ex, device, codec.pad)
        preds = greedy(model, codec, [c.prompt for c in val_cases])
        report = evaluate(val_cases, {c.id: p.text for c, p in zip(val_cases, preds, strict=True)})
        row = {
            "epoch": epoch,
            "step": step,
            "lr": opt.param_groups[0]["lr"],
            "train_loss": round(train_sum / max(1, train_n), 5),
            "val_loss": round(vl, 5),
            "val_exact": report["exact_rate"],
            "val_by_category": {k: v["exact_rate"] for k, v in report["by_category"].items()},
            "elapsed_s": round(time.monotonic() - t0, 1),
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row))
        if (row["val_exact"], -vl) > (best["val_exact"], -best["val_loss"]):
            best = {"val_exact": row["val_exact"], "val_loss": vl, "epoch": epoch, "step": step}
            save(out / "best.pt", model, codec, {"epoch": epoch, "step": step, "args": vars(args)})

    save(out / "last.pt", model, codec, {"epoch": epoch, "step": step, "args": vars(args)})
    summary = {
        "size": args.size,
        "params": n_params,
        "config": cfg.to_dict(),
        "tokenizer": {"file": Path(args.tokenizer).name, "sha256": codec.sha256},
        "train_examples": len(train_ex),
        "val_examples": len(val_ex),
        "steps": step,
        "epochs": epoch,
        "best": best,
        "train_seconds": round(time.monotonic() - t0, 1),
        "device": str(device),
        "torch": torch.__version__,
        "args": vars(args),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--size", choices=sorted(SIZES), required=True)
    p.add_argument("--tokenizer", required=True)
    p.add_argument("--data", default=str(PROJECT_ROOT / "datasets/action/v0"))
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--max-steps", type=int, default=0, help="override epochs (smoke tests)")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--min-lr-ratio", type=float, default=0.1)
    p.add_argument("--warmup", type=int, default=200)
    p.add_argument("--weight-decay", type=float, default=0.1)
    p.add_argument("--dropout", type=float, default=0.1)
    p.add_argument("--eval-every", type=int, default=2, help="epochs between validations")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--device", default="auto")
    return p


def main(argv: list[str] | None = None) -> None:
    train(build_parser().parse_args(argv))


if __name__ == "__main__":
    main()
