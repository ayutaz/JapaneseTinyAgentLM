"""Job definitions for vast.ai (see jtalm.infra.job for the runner)."""

from jtalm.infra.spec import JobSpec

VLLM_IMAGE = "vllm/vllm-openai:v0.30.0"  # CUDA 13.0, so hosts need cuda_vers >= 13.0
UV = "$HOME/.local/bin/uv"
BASE_QUERY = (
    "num_gpus=1 cuda_vers>=13.0 reliability>0.98 inet_down>=500 disk_space>=120 "
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


def generate(phase: str) -> str:
    return f"{UV} run --no-dev python -m jtalm.data.generate --phase {phase} --workers 64"


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
        STOP_VLLM,
        start_vllm(EVAL_MODEL, gpu_mem=0.9, max_len=4096, extra="--served-model-name llmjp"),
        generate("train-verify"),
    ],
)

JOBS: dict[str, JobSpec] = {job.name: job for job in (SMOKE, GEN_ACTION_V0)}
