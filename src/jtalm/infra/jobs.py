"""Job definitions for vast.ai (see jtalm.infra.job for the runner)."""

from jtalm.infra.spec import JobSpec

VLLM_IMAGE = "vllm/vllm-openai:v0.30.0"  # CUDA 13.0, so hosts need cuda_vers >= 13.0
UV = "$HOME/.local/bin/uv"


def sync(extra: str = "") -> str:
    """``uv sync`` with retries: a host's connection dropped mid-download of torch once."""
    cmd = f"{UV} sync --locked --no-dev {extra}".strip()
    return f"for i in 1 2 3; do {cmd} && exit 0; sleep 15; done; exit 1"


BASE_QUERY = (
    "num_gpus=1 cuda_vers>=13.0 reliability>0.98 inet_down>=1000 disk_space>=120 "
    "rentable=true direct_port_count>=1 verified=true"
)


def start_vllm(model: str, gpu_mem: float, max_len: int, extra: str = "", port: int = 8000) -> str:
    """Start an OpenAI-compatible vLLM server in the background and wait until it is healthy.

    The wait covers the weight download: up to 30 minutes (360 x 5 s). A 15-minute limit was too
    short for 45-65GB writers on a slow host (gen_action_v051, 2026-09-30).
    """
    return (
        'VLLM="$(command -v vllm || echo "python3 -m vllm.entrypoints.cli.main")"; '
        f"setsid nohup $VLLM serve {model} --port {port} --gpu-memory-utilization {gpu_mem} "
        f"--max-model-len {max_len} {extra} > artifacts/vllm-{port}.log 2>&1 < /dev/null & "
        "for i in $(seq 1 360); do "
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
        sync("--group train"),
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
        f"--config {config} --workers 256" + (f" --out {out}" if out else "")
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
        sync(),
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
        sync(),
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
    runs: list[tuple[str, str, str]], tag: str, data: str = ACTION_DATA, parallel: bool = False
) -> list[str]:
    """Train each run, then evaluate all of them on the v0 evaluation set (never changes).

    With ``parallel`` all runs start at once on the same GPU. A 3M-20M model at batch 64 uses
    under 1GB of VRAM and leaves the GPU mostly idle, so this cuts wall-clock time several-fold
    without changing any hyperparameter (results stay comparable with sequential runs).
    """
    ckpts = " ".join(f"artifacts/{tag}/{name}/best.pt" for name, _, _ in runs)
    cmds = [
        f"{TRAIN} --data {data} --size {size} {extra} --out artifacts/{tag}/{name} "
        f"> artifacts/{tag}-{name}.log 2>&1"
        for name, size, extra in runs
    ]
    if parallel:
        launch = " ".join(f"({c}) & pids+=($!);" for c in cmds)
        cmds = [
            f"pids=(); {launch} fail=0; for p in ${{pids[@]}}; do wait $p || fail=1; done; "
            "exit $fail"
        ]
    return [
        "nvidia-smi > artifacts/nvidia_smi.txt",
        sync("--group train"),
        *cmds,
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
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", sync()]
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

# Data v0.4 (after the scaling check): many writers at once, about 48k requested sentences.
# More sentences from the same writer stopped helping beyond 50% of v0 (results/data_scaling_v0),
# so v0.4 scales through new writer families. Weights are deleted after each writer (disk), a
# failing writer does not stop the others, and Qwen3 (also a writer) verifies everything at the end.
V04_WRITERS = [
    # (name, hf_id, gpu memory fraction)
    ("abeja", "abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0", 0.92),  # Apache-2.0, 65GB
    ("nemoja", "cyberagent/Mistral-Nemo-Japanese-Instruct-2408", 0.9),  # Apache-2.0, 25GB
    ("granite", "ibm-granite/granite-3.3-8b-instruct", 0.9),  # Apache-2.0, 16GB
    ("elyza", "elyza/ELYZA-Shortcut-1.0-Qwen-32B", 0.92),  # Apache-2.0, 65GB
    ("calm3", "cyberagent/calm3-22b-chat", 0.9),  # Apache-2.0, 45GB
    ("sarashina", "sbintuitions/sarashina2.2-3b-instruct-v0.1", 0.5),  # MIT, 7GB
]
HF_CACHE = "$HOME/.cache/huggingface/hub"


def _drop_weights(hf_id: str) -> str:
    """Delete a writer's weights and the hf_xet chunk cache, and log free disk space.

    In gen_action_v04 the disk (200GB) still filled up after four writers, so ELYZA, calm3 and
    Qwen3 could not be downloaded; the xet cache is now removed too and ``df`` is logged.
    """
    return (
        f"rm -rf {HF_CACHE}/models--{hf_id.replace('/', '--')} $HOME/.cache/huggingface/xet; "
        "df -h / /root 2>/dev/null | tail -n 2"
    )


def _v04_steps() -> list[str]:
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", sync()]
    for name, hf_id, mem in V04_WRITERS:
        cfg = f"configs/action_v04_{name}.json"
        start = start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}")
        gen = generate("train-gen", cfg, f"artifacts/raw04_{name}")
        steps += [
            f"({start}) && ({gen}) || echo 'writer {name} failed' >> artifacts/failed_writers.txt",
            f"{STOP_VLLM}; {_drop_weights(hf_id)}",
        ]
    steps += [
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", "configs/action_v04_qwen.json", "artifacts/raw04_qwen"),
    ]
    for name in [n for n, _, _ in V04_WRITERS] + ["qwen"]:
        out = f"artifacts/raw04_{name}"
        verify = generate("train-verify", f"configs/action_v04_{name}.json", out)
        steps.append(f"if [ -s {out}/train_gen.jsonl ]; then {verify}; fi")
    return steps


GEN_ACTION_V04 = JobSpec(
    name="gen_action_v04",
    description="Data v0.4: seven writers (~48k sentences) for the train data, Qwen3 verifies",
    query=f"gpu_ram>=79 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=200,
    max_hours=3.0,
    steps=_v04_steps(),
)

# v0.4b: finish v0.4 after the disk ran out. The four writers that succeeded (ABEJA,
# Mistral-Nemo-JA, granite, sarashina2.2) are uploaded from datasets/raw/v04 (gitignored) and only
# verified; ELYZA, calm3 and Qwen3 write again on a larger disk.
V04B_DONE = ["abeja", "nemoja", "granite", "sarashina"]
V04B_WRITERS = [w for w in V04_WRITERS if w[0] in ("elyza", "calm3")]


def _v04b_steps() -> list[str]:
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", "df -h /", sync()]
    for name, hf_id, mem in V04B_WRITERS:
        cfg = f"configs/action_v04_{name}.json"
        start = start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}")
        gen = generate("train-gen", cfg, f"artifacts/raw04_{name}")
        steps += [
            f"({start}) && ({gen}) || echo 'writer {name} failed' >> artifacts/failed_writers.txt",
            f"{STOP_VLLM}; {_drop_weights(hf_id)}",
        ]
    steps += [
        "mkdir -p artifacts && cp -r datasets/raw/v04/raw04_* artifacts/",
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", "configs/action_v04_qwen.json", "artifacts/raw04_qwen"),
    ]
    for name in V04B_DONE + [n for n, _, _ in V04B_WRITERS] + ["qwen"]:
        out = f"artifacts/raw04_{name}"
        verify = generate("train-verify", f"configs/action_v04_{name}.json", out)
        steps.append(f"if [ -s {out}/train_gen.jsonl ]; then {verify}; fi")
    return steps


GEN_ACTION_V04B = JobSpec(
    name="gen_action_v04b",
    description="Data v0.4 (finish): ELYZA / calm3 / Qwen3 write, Qwen3 verifies all seven writers",
    query=f"gpu_ram>=79 {BASE_QUERY}".replace("disk_space>=120", "disk_space>=320"),
    image=VLLM_IMAGE,
    disk_gb=300,
    max_hours=2.5,
    steps=_v04b_steps(),
    uploads=[f"datasets/raw/v04/raw04_{w}/train_gen.jsonl" for w in V04B_DONE],
)

# Human-written evaluation set (jtalm.data.human_eval): Qwen3 parses the mined candidates at
# temperature 0; only items whose parse equals the rule label are kept. The candidates file is
# gitignored (it holds third-party sentences) and uploaded by scp.
HUMAN_RAW = "datasets/raw/human_v1"
VERIFY_HUMAN_V1 = JobSpec(
    name="verify_human_v1",
    description="Human-written eval set: Qwen3 verifies mined candidates (rule label must agree)",
    query=f"gpu_ram>=79 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=160,
    max_hours=1.0,
    steps=[
        sync(),
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-verify", "configs/human_eval_v1.json", HUMAN_RAW),
        f"mkdir -p artifacts/raw_human && cp {HUMAN_RAW}/train_raw.jsonl artifacts/raw_human/",
    ],
    uploads=[f"{HUMAN_RAW}/train_gen.jsonl"],
)

# Evaluation set v2: llm-jp-3.1 (the eval-only writer) writes one slice per phrasing pattern
# (jtalm.data.focus), Qwen3 verifies at temperature 0. Never used for training.
GEN_EVAL_V2 = JobSpec(
    name="gen_eval_v2",
    description="Eval set v2: llm-jp writes focused slices (12 patterns), Qwen3 verifies",
    query=f"gpu_ram>=79 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=160,
    max_hours=1.5,
    steps=[
        "nvidia-smi > artifacts/nvidia_smi.txt",
        sync(),
        start_vllm(EVAL_MODEL, gpu_mem=0.9, max_len=4096, extra="--served-model-name llmjp"),
        generate("eval-gen", "configs/eval_v2.json", "artifacts/raw_eval_v2"),
        f"{STOP_VLLM}; {_drop_weights(EVAL_MODEL)}",
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("eval-verify", "configs/eval_v2.json", "artifacts/raw_eval_v2"),
    ],
)

# Data v0.5 (after the human-written evaluation): the seven training writers write the focused
# slices (jtalm.data.focus), and the v0.4 3M model mines hard negatives from human-written text
# outside the evaluation pool; Qwen3 verifies everything at temperature 0.
# The checkpoint is the output of the train_action_v04 job on the maintainer's machine (runs/ is
# gitignored); to rerun this job, point it at your own train_action_v04 output.
V04_CKPT = "runs/vast/train_action_v04-20260929T095441Z/artifacts/v04/3m/best.pt"
MINE_POOL = "datasets/raw/mine_pool/pool.jsonl"


def _v05_steps() -> list[str]:
    steps = [
        "nvidia-smi > artifacts/nvidia_smi.txt",
        "df -h /",
        sync("--group train"),
        f"{UV} run --no-dev --group train python -m jtalm.model.mine --ckpt {V04_CKPT} "
        f"--tokenizer {TOKENIZER} --pool {MINE_POOL} --out artifacts/raw05_mined",
    ]
    for name, hf_id, mem in V04_WRITERS:
        cfg = f"configs/action_v05_{name}.json"
        start = start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}")
        gen = generate("train-gen", cfg, f"artifacts/raw05_{name}")
        steps += [
            f"({start}) && ({gen}) || echo 'writer {name} failed' >> artifacts/failed_writers.txt",
            f"{STOP_VLLM}; {_drop_weights(hf_id)}",
        ]
    steps += [
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", "configs/action_v05_qwen.json", "artifacts/raw05_qwen"),
    ]
    for name in [n for n, _, _ in V04_WRITERS] + ["qwen", "mined"]:
        out = f"artifacts/raw05_{name}"
        verify = generate("train-verify", f"configs/action_v05_{name}.json", out)
        steps.append(f"if [ -s {out}/train_gen.jsonl ]; then {verify}; fi")
    return steps


GEN_ACTION_V05 = JobSpec(
    name="gen_action_v05",
    description="Data v0.5: focused slices by seven writers + mined hard negatives, Qwen3 verifies",
    query=f"gpu_ram>=79 {BASE_QUERY}".replace("disk_space>=120", "disk_space>=320"),
    image=VLLM_IMAGE,
    disk_gb=300,
    max_hours=3.0,
    steps=_v05_steps(),
    uploads=[V04_CKPT, MINE_POOL, TOKENIZER],
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
    steps=train_action_steps(V03_RUNS, "v03", ACTION_DATA_V03, parallel=True),
    uploads=[
        f"{ACTION_DATA_V03}/train.jsonl",
        f"{ACTION_DATA_V03}/val.jsonl",
        f"{ACTION_DATA}/eval.jsonl",
        TOKENIZER,
    ],
)

# Retrain on v0.4 (v0.3 plus seven writers, about 49k examples). 15 epochs keep the step count
# at about twice M4's; all runs share one GPU in parallel.
ACTION_DATA_V04 = "datasets/action/v0.4"
V04_RUNS = [
    ("3m", "3m", "--lr 1e-3 --epochs 15"),
    ("3m-s1", "3m", "--lr 1e-3 --epochs 15 --seed 1"),
    ("5m", "5m", "--lr 1e-3 --epochs 15"),
    ("5m-s1", "5m", "--lr 1e-3 --epochs 15 --seed 1"),
    ("20m", "20m", "--lr 6e-4 --epochs 15"),
]
TRAIN_ACTION_V04 = JobSpec(
    name="train_action_v04",
    description="Train 3M / 5M / 20M on data v0.4 in parallel; evaluate on the v0 eval set",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=4.0,
    steps=train_action_steps(V04_RUNS, "v04", ACTION_DATA_V04, parallel=True),
    uploads=[
        f"{ACTION_DATA_V04}/train.jsonl",
        f"{ACTION_DATA_V04}/val.jsonl",
        f"{ACTION_DATA}/eval.jsonl",
        TOKENIZER,
    ],
)

# Retrain on v0.5 (v0.4 plus focused slices and mined hard negatives, about 65k examples).
ACTION_DATA_V05 = "datasets/action/v0.5"
V05_RUNS = [
    ("3m", "3m", "--lr 1e-3 --epochs 12"),
    ("3m-s1", "3m", "--lr 1e-3 --epochs 12 --seed 1"),
    ("5m", "5m", "--lr 1e-3 --epochs 12"),
]
TRAIN_ACTION_V05 = JobSpec(
    name="train_action_v05",
    description="Train 3M (x2) and 5M on data v0.5 in parallel; evaluate on the v0 eval set",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=4.0,
    steps=train_action_steps(V05_RUNS, "v05", ACTION_DATA_V05, parallel=True),
    uploads=[
        f"{ACTION_DATA_V05}/train.jsonl",
        f"{ACTION_DATA_V05}/val.jsonl",
        f"{ACTION_DATA}/eval.jsonl",
        TOKENIZER,
    ],
)

# Data v0.5.1: a small top-up after v0.5 (rough imperatives, 下さい in kanji, corrections)
# written by three writers; then retrain 3M on v0.5 + the top-up.
V051_WRITERS = [w for w in V04_WRITERS if w[0] in ("abeja", "calm3")]


def _v051_steps() -> list[str]:
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", "df -h /", sync()]
    for name, hf_id, mem in V051_WRITERS:
        cfg = f"configs/action_v051_{name}.json"
        start = start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}")
        gen = generate("train-gen", cfg, f"artifacts/raw051_{name}")
        steps += [
            f"({start}) && ({gen}) || echo 'writer {name} failed' >> artifacts/failed_writers.txt",
            f"{STOP_VLLM}; {_drop_weights(hf_id)}",
        ]
    steps += [
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", "configs/action_v051_qwen.json", "artifacts/raw051_qwen"),
    ]
    for name in [n for n, _, _ in V051_WRITERS] + ["qwen"]:
        out = f"artifacts/raw051_{name}"
        verify = generate("train-verify", f"configs/action_v051_{name}.json", out)
        steps.append(f"if [ -s {out}/train_gen.jsonl ]; then {verify}; fi")
    return steps


GEN_ACTION_V051 = JobSpec(
    name="gen_action_v051",
    description="Data v0.5.1 top-up: imperatives, 下さい, corrections (3 writers, Qwen3 checks)",
    query=f"gpu_ram>=79 {BASE_QUERY}".replace("disk_space>=120", "disk_space>=200"),
    image=VLLM_IMAGE,
    disk_gb=200,
    max_hours=2.0,
    steps=_v051_steps(),
)


# v0.5.1b: rerun the two writers that timed out (ABEJA, calm3), then let Qwen3 verify them.
def _v051b_steps() -> list[str]:
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", "df -h /", sync()]
    for name, hf_id, mem in V051_WRITERS:
        cfg = f"configs/action_v051_{name}.json"
        start = start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}")
        gen = generate("train-gen", cfg, f"artifacts/raw051_{name}")
        steps += [
            f"({start}) && ({gen}) || echo 'writer {name} failed' >> artifacts/failed_writers.txt",
            f"{STOP_VLLM}; {_drop_weights(hf_id)}",
        ]
    steps.append(
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen")
    )
    for name, _, _ in V051_WRITERS:
        out = f"artifacts/raw051_{name}"
        verify = generate("train-verify", f"configs/action_v051_{name}.json", out)
        steps.append(f"if [ -s {out}/train_gen.jsonl ]; then {verify}; fi")
    return steps


GEN_ACTION_V051B = JobSpec(
    name="gen_action_v051b",
    description="Data v0.5.1 (rerun): ABEJA and calm3 write the top-up slices, Qwen3 verifies",
    query=f"gpu_ram>=79 {BASE_QUERY}".replace("disk_space>=120", "disk_space>=200"),
    image=VLLM_IMAGE,
    disk_gb=200,
    max_hours=2.5,
    steps=_v051b_steps(),
)

ACTION_DATA_V051 = "datasets/action/v0.5.1"
TRAIN_ACTION_V051 = JobSpec(
    name="train_action_v051",
    description="Train 3M (x2) on data v0.5.1 in parallel; evaluate on the v0 eval set",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=4.0,
    steps=train_action_steps(V05_RUNS[:2], "v051", ACTION_DATA_V051, parallel=True),
    uploads=[
        f"{ACTION_DATA_V051}/train.jsonl",
        f"{ACTION_DATA_V051}/val.jsonl",
        f"{ACTION_DATA}/eval.jsonl",
        TOKENIZER,
    ],
)

# Seed spread on v0.5.1: three more 3M seeds (with seeds 0 and 1 from train_action_v051, five
# in total) so that model comparisons can report a mean and a spread instead of one run.
V051_SEED_RUNS = [(f"3m-s{i}", "3m", f"--lr 1e-3 --epochs 12 --seed {i}") for i in (2, 3, 4)]
TRAIN_ACTION_V051_SEEDS = JobSpec(
    name="train_action_v051_seeds",
    description="Three more 3M seeds on data v0.5.1 (seed spread for error bars)",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=3.0,
    steps=train_action_steps(V051_SEED_RUNS, "v051s", ACTION_DATA_V051, parallel=True),
    uploads=TRAIN_ACTION_V051.uploads,
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
        GEN_ACTION_V04,
        GEN_ACTION_V04B,
        TRAIN_ACTION_V04,
        VERIFY_HUMAN_V1,
        GEN_EVAL_V2,
        GEN_ACTION_V05,
        TRAIN_ACTION_V05,
        GEN_ACTION_V051,
        GEN_ACTION_V051B,
        TRAIN_ACTION_V051,
        TRAIN_ACTION_V051_SEEDS,
    )
}
