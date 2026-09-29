"""Job definitions for vast.ai (see jtalm.infra.job for the runner)."""

from jtalm.infra.spec import JobSpec

VLLM_IMAGE = "vllm/vllm-openai:v0.30.0"  # CUDA 13.0, so hosts need cuda_vers >= 13.0
UV = "$HOME/.local/bin/uv"
BASE_QUERY = (
    "num_gpus=1 cuda_vers>=13.0 reliability>0.98 inet_down>=1000 disk_space>=120 "
    "rentable=true direct_port_count>=1 verified=true"
)


def start_vllm(model: str, gpu_mem: float, max_len: int, extra: str = "", port: int = 8000) -> str:
    """Start an OpenAI-compatible vLLM server in the background and wait until it is healthy."""
    return (
        'VLLM="$(command -v vllm || echo "python3 -m vllm.entrypoints.cli.main")"; '
        f"setsid nohup $VLLM serve {model} --port {port} --gpu-memory-utilization {gpu_mem} "
        f"--max-model-len {max_len} {extra} > artifacts/vllm-{port}.log 2>&1 < /dev/null & "
        "for i in $(seq 1 180); do "
        f"curl -sf localhost:{port}/health > /dev/null && break; sleep 5; done; "
        f"curl -sf localhost:{port}/health > /dev/null"
    )


SMOKE = JobSpec(
    name="smoke",
    description="M2.5: GPU torch check (train group) and a tiny vLLM generation with Qwen3-0.6B",
    query=f"gpu_ram>=24 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=1.0,
    steps=[
        "nvidia-smi > artifacts/nvidia_smi.txt",
        f"{UV} sync --locked --no-dev --group train",
        f"{UV} run --no-dev --group train python -m jtalm.infra.gpu_check "
        "> artifacts/gpu_check.json",
        start_vllm("Qwen/Qwen3-0.6B", gpu_mem=0.5, max_len=4096),
        f"{UV} run --no-dev python -m jtalm.data.smoke_generate "
        "--base-url http://localhost:8000/v1 --model Qwen/Qwen3-0.6B "
        "--out artifacts/gen_smoke.jsonl",
    ],
)

STOP_VLLM = (
    "pkill -f '[v]llm serve' || true; "
    "for i in $(seq 1 60); do "
    "nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q . || break; sleep 5; done"
)
TRAIN_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"  # Apache-2.0, bf16 61GB
EVAL_MODEL = "llm-jp/llm-jp-3.1-13b-instruct4"  # Apache-2.0, bf16 ~27GB


def generate(phase: str, config: str = "configs/action_v0.json", out: str = "") -> str:
    return (
        f"{UV} run --no-dev python -m jtalm.data.generate --phase {phase} "
        f"--config {config} --workers 64" + (f" --out {out}" if out else "")
    )


GEN_ACTION_V0 = JobSpec(
    name="gen_action_v0",
    description="M3: generate and cross-verify synthetic Action data (one model at a time)",
    query=f"gpu_ram>=79 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=200,
    max_hours=3.0,
    steps=[
        "nvidia-smi > artifacts/nvidia_smi.txt",
        f"{UV} sync --locked --no-dev",
        start_vllm(EVAL_MODEL, gpu_mem=0.9, max_len=4096, extra="--served-model-name llmjp"),
        generate("eval-gen"),
        STOP_VLLM,
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen"),
        generate("eval-verify"),
        generate("train-verify"),  # v0.2: train sentences are verified by Qwen3 (temperature 0)
    ],
)

TOPUP_CONFIG = "configs/action_v0_negation_topup.json"
GEN_ACTION_V0_NEGATION = JobSpec(
    name="gen_action_v0_negation",
    description="M3: negation-only top-up for action-v0 (Qwen3 writes and verifies)",
    query=f"gpu_ram>=79 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=160,
    max_hours=1.0,
    steps=[
        f"{UV} sync --locked --no-dev",
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", TOPUP_CONFIG),
        generate("train-verify", TOPUP_CONFIG),
    ],
)

TOKENIZER = "tokenizer/out/action_v0_sp2048.model"
ACTION_DATA = "datasets/action/v0"
TRAIN = f"{UV} run --no-dev --group train python -m jtalm.model.train --tokenizer {TOKENIZER}"
# (run name, size, extra args). Seeds 1-2 of 5M measure run-to-run variance.
TRAIN_RUNS = [
    ("3m", "3m", "--lr 1e-3"),
    ("5m", "5m", "--lr 1e-3"),
    ("20m", "20m", "--lr 6e-4"),
    ("5m-s1", "5m", "--lr 1e-3 --seed 1"),
    ("5m-s2", "5m", "--lr 1e-3 --seed 2"),
]


def train_action_steps(
    runs: list[tuple[str, str, str]], tag: str, data: str = ACTION_DATA
) -> list[str]:
    """Train each run, then evaluate all of them on the v0 evaluation set (never changes)."""
    ckpts = " ".join(f"artifacts/{tag}/{name}/best.pt" for name, _, _ in runs)
    return [
        "nvidia-smi > artifacts/nvidia_smi.txt",
        f"{UV} sync --locked --no-dev --group train",
        *(
            f"{TRAIN} --data {data} --size {size} {extra} --out artifacts/{tag}/{name} "
            f"> artifacts/{tag}-{name}.log 2>&1"
            for name, size, extra in runs
        ),
        f"{UV} run --no-dev --group train python -m jtalm.model.evaluate --ckpt {ckpts} "
        f"--tokenizer {TOKENIZER} --cases {ACTION_DATA}/eval.jsonl --out artifacts/{tag}/eval",
    ]


# compute_cap 800-900 (Ampere to Hopper): the cu126 torch wheels have no Blackwell (sm_120)
# kernels, so an RTX PRO 4000 host failed on the first training step (2026-09-29).
# The vLLM image is reused because SSH, curl, and the driver setup are proven on vast.ai (M2.5);
# torch comes from the cu126 wheels via ``uv sync``, not from the image.
TRAIN_ACTION_V0 = JobSpec(
    name="train_action_v0",
    description="M4: train 3M / 5M / 20M Action LMs from scratch and evaluate them",
    query=f"gpu_ram>=24 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=2.0,
    steps=train_action_steps(TRAIN_RUNS, "m4"),
    uploads=[
        f"{ACTION_DATA}/train.jsonl",
        f"{ACTION_DATA}/val.jsonl",
        f"{ACTION_DATA}/eval.jsonl",
        TOKENIZER,
    ],
)

# Data v0.3 (after M4): more writers for the TRAIN data only; the eval set is not regenerated.
# Each writer is served alone, then Qwen3 verifies every sentence at temperature 0.
V03_WRITERS = [
    # (name, hf_id, gpu memory fraction)
    ("calm3", "cyberagent/calm3-22b-chat", 0.9),  # Apache-2.0, 45GB bf16
    ("sarashina", "sbintuitions/sarashina2.2-3b-instruct-v0.1", 0.5),  # MIT, 6.7GB
]


def _v03_steps() -> list[str]:
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", f"{UV} sync --locked --no-dev"]
    for name, hf_id, mem in V03_WRITERS:
        cfg = f"configs/action_v03_{name}.json"
        steps += [
            start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}"),
            generate("train-gen", cfg, f"artifacts/raw_{name}"),
            STOP_VLLM,
        ]
    steps += [
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", "configs/action_v03_qwen.json", "artifacts/raw_qwen"),
    ]
    for name in [n for n, _, _ in V03_WRITERS] + ["qwen"]:
        steps.append(
            generate("train-verify", f"configs/action_v03_{name}.json", f"artifacts/raw_{name}")
        )
    return steps


GEN_ACTION_V03 = JobSpec(
    name="gen_action_v03",
    description="Data v0.3: calm3 / sarashina2.2 / Qwen3 write train sentences, Qwen3 verifies",
    query=f"gpu_ram>=79 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=200,
    max_hours=2.5,
    steps=_v03_steps(),
)

# Retrain on v0.3 (v0 plus the new writers) and compare with M4 on the same evaluation set.
ACTION_DATA_V03 = "datasets/action/v0.3"
V03_RUNS = [
    ("3m", "3m", "--lr 1e-3"),
    ("3m-s1", "3m", "--lr 1e-3 --seed 1"),
    ("5m", "5m", "--lr 1e-3"),
    ("5m-s1", "5m", "--lr 1e-3 --seed 1"),
    ("20m", "20m", "--lr 6e-4"),
]
TRAIN_ACTION_V03 = JobSpec(
    name="train_action_v03",
    description="Train 3M / 5M / 20M on data v0.3 and evaluate on the unchanged v0 eval set",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=3.0,
    steps=train_action_steps(V03_RUNS, "v03", ACTION_DATA_V03),
    uploads=[
        f"{ACTION_DATA_V03}/train.jsonl",
        f"{ACTION_DATA_V03}/val.jsonl",
        f"{ACTION_DATA}/eval.jsonl",
        TOKENIZER,
    ],
)

# Data-scaling check (after M4): 3M on 25 / 50 / 100% of the v0 training data with the same
# number of optimizer steps as M4 (5,680), so only the amount of data changes.
SCALING_STEPS = "--lr 1e-3 --max-steps 5680"
SCALING_RUNS = [
    ("3m-f025", "3m", f"{SCALING_STEPS} --train-fraction 0.25"),
    ("3m-f025-s1", "3m", f"{SCALING_STEPS} --train-fraction 0.25 --seed 1"),
    ("3m-f050", "3m", f"{SCALING_STEPS} --train-fraction 0.5"),
    ("3m-f050-s1", "3m", f"{SCALING_STEPS} --train-fraction 0.5 --seed 1"),
    ("3m-f100-s1", "3m", f"{SCALING_STEPS} --seed 1"),
]
TRAIN_ACTION_V0_SCALING = JobSpec(
    name="train_action_v0_scaling",
    description="After M4: does more v0 data help? 3M on 25/50/100% of the training data",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=2.0,
    steps=train_action_steps(SCALING_RUNS, "scaling"),
    uploads=TRAIN_ACTION_V0.uploads,
)

JOBS: dict[str, JobSpec] = {
    job.name: job
    for job in (
        SMOKE,
        GEN_ACTION_V0,
        GEN_ACTION_V0_NEGATION,
        TRAIN_ACTION_V0,
        TRAIN_ACTION_V0_SCALING,
        GEN_ACTION_V03,
        TRAIN_ACTION_V03,
    )
}
