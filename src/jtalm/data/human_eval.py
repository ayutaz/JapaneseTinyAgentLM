# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Human-written evaluation set (after M4): mine and label real Japanese sentences.

No public dataset has human-written Japanese requests to a robot to turn its head, nod, or
change its face (research on 2026-09-29), so positives are mined from human-written corpora
(Tatoeba, JESC subtitles) with a strict whole-sentence pattern: the sentence must consist only
of an optional interjection, the action phrase(s), and a request ending. The pattern that matched
defines the label. Negated requests (向かないで, 笑わないで ...) become ``[]`` negation cases.
No-action negatives come from real assistant / robot / chatbot logs (YJ_AmbigDialogue, J-CRe3,
DSLC3) and MASSIVE ja-JP test. Every candidate is then parsed by Qwen3 at temperature 0
(``jtalm.data.generate --phase train-verify``) and only agreeing items are kept.

The sentences are addressed to people, not robots: report scores as "human-written requests".
Nothing here is redistributed; ``datasets/`` holds local copies only.

    uv run python -m jtalm.data.human_eval candidates   # -> datasets/raw/human_v1/train_gen.jsonl
    uv run python -m jtalm.data.human_eval build --raw <run>/artifacts/raw_human
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from jtalm.action.schema import Call, canonicalize, validate
from jtalm.data import massive
from jtalm.data.checks import dedup_key, normalize
from jtalm.eval.cases import EvalCase, load_cases, write_cases
from jtalm.infra.env import PROJECT_ROOT

DOWNLOADS = PROJECT_ROOT / "datasets/downloads/human_eval"
DEFAULT_HUMAN_EVAL = PROJECT_ROOT / "datasets/action/human_v1/eval.jsonl"
MAX_CHARS = 30

SOURCES = {
    "tatoeba": {"url": "https://tatoeba.org/en/downloads", "license": "CC BY 2.0 FR"},
    "jesc": {"url": "https://nlp.stanford.edu/projects/jesc/", "license": "CC BY-SA 4.0"},
    "yj_ambig": {"url": "https://github.com/yahoojapan/YJ_AmbigDialogue", "license": "CC BY 4.0"},
    "jcre3": {"url": "https://github.com/riken-grp/J-CRe3", "license": "CC BY-SA 4.0"},
    "dslc3": {
        "url": "https://dialog-system-live-competition.github.io/dslc3/data.html",
        "license": "MIT",
    },
    "massive": {"url": massive.MASSIVE_URL, "license": massive.MASSIVE_LICENSE},
}

# ---- whole-sentence request grammar ----------------------------------------------------------

PREFIX = r"(?:ほら|ねえ|ねぇ|さあ|おい|ちょっと|もう一度|もういちど)?[、,]?"
AMOUNT = {"slight": r"少し|すこし|ちょっと|軽く|ちょこっと", "large": r"大きく|思いっきり|思い切り"}
DIRECTION = [
    ("center", r"こっち|こちら|私の方|僕の方|俺の方|前|正面|まっすぐ|真っ直ぐ"),
    ("right", r"右"),
    ("left", r"左"),
    ("up", r"上"),
    ("down", r"下"),
]
LOOK_VERB = r"(?:を|の方を|の方|へ|に)?(?:向いて|向け|向きなさい|見て|見ろ|見なさい)"
EXTRA_LOOK = [
    ("up", r"見上げて|顔を上げ(?:て|ろ|なさい)|顔上げて"),
    ("down", r"うつむいて|俯いて|下を向いて"),
    ("center", r"顔を(?:こっちに|こちらに|こっち|こちら)?向けて"),
]
EXPRESSION = [
    (
        "happy",
        r"笑って|笑え|笑顔(?:を見せて|になって|で)?|にっこり(?:して|笑って)?|微笑んで|ほほえんで",
    ),
    ("sad", r"悲しい顔(?:を)?して|悲しそうな顔(?:を)?して"),
    ("surprised", r"驚いた顔(?:を)?して|びっくりした顔(?:を)?して"),
    ("neutral", r"真顔(?:に)?(?:なって|して)"),
]
NOD = r"(?:うなず|頷)(?:いて|け|きなさい)|首を縦に振って"
COUNT = {"2": r"(?:2|２|二)回", "3": r"(?:3|３|三)回"}
CONNECT = r"(?:、|,|そして|それから|から)?"
END = (
    r"(?:ください|下さい|くれ|くれる|くれない|ちょうだい|よ|ね|な|なさい)?(?:よ|ね)?"
    r"[!！?？。．…〜ー]*"
)
NEGATED = re.compile(
    r"^" + PREFIX + r"(?:" + "|".join(d for _, d in DIRECTION) + r")?(?:を|の方を|の方|へ|に)?"
    r"(?:向かないで|見ないで|笑わないで|うなずかないで|頷かないで)"
    r"(?:ください|下さい|くれ|よ|ね)?[!！?？。．…〜ー]*$"
)
ANY_GESTURE = re.compile(r"向いて|向け|向か|うなず|頷|笑|にっこり|微笑|顔して|見上げ|うつむ|首を")


def _match_action(s: str) -> tuple[Call, str] | None:
    """Match one action at the start of ``s``; return (call, rest)."""
    amount = "normal"
    for name, pat in AMOUNT.items():
        m = re.match(pat, s)
        if m:
            amount, s = name, s[m.end() :]
            break
    for direction, pat in DIRECTION:
        m = re.match(f"(?:{pat}){LOOK_VERB}", s)
        if m:
            amt = "normal" if direction == "center" else amount
            return {"name": "look", "arguments": {"direction": direction, "amount": amt}}, s[
                m.end() :
            ]
    for direction, pat in EXTRA_LOOK:
        m = re.match(pat, s)
        if m:
            args = {"direction": direction, "amount": amount}
            return {"name": "look", "arguments": args}, s[m.end() :]
    if amount != "normal":
        return None  # an amount word must modify a look
    count = 1
    for n, pat in COUNT.items():
        m = re.match(pat, s)
        if m:
            count, s = int(n), s[m.end() :]
            break
    m = re.match(NOD, s)
    if m:
        return {"name": "nod", "arguments": {"count": count}}, s[m.end() :]
    if count != 1:
        return None
    for expression, pat in EXPRESSION:
        m = re.match(pat, s)
        if m:
            return {"name": "set_expression", "arguments": {"expression": expression}}, s[m.end() :]
    return None


def parse_request(text: str) -> list[Call] | None:
    """Label a whole-sentence gesture request, or None if the sentence is anything else."""
    s = re.sub(r"\s+", "", normalize(text))
    if not s or len(s) > MAX_CHARS:
        return None
    m = re.match(PREFIX, s)
    s = s[m.end() :] if m else s
    calls: list[Call] = []
    while len(calls) < 2:
        hit = _match_action(s)
        if hit is None:
            break
        call, s = hit
        calls.append(call)
        c = re.match(CONNECT, s)
        s = s[c.end() :] if c else s
    if not calls or not re.fullmatch(END, s):
        return None
    calls = canonicalize(calls)
    return calls if not validate(calls) else None


def is_negated_request(text: str) -> bool:
    s = re.sub(r"\s+", "", normalize(text))
    return len(s) <= MAX_CHARS and bool(NEGATED.match(s))


# ---- sources ---------------------------------------------------------------------------------


def tatoeba_sentences(root: Path) -> list[str]:
    path = root / "jpn_sentences.tsv"
    return [line.rstrip("\n").split("\t")[-1] for line in path.open(encoding="utf-8")]


def jesc_sentences(root: Path) -> list[str]:
    out = []
    with (root / "raw/raw").open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            ja = line.rstrip("\n").split("\t")[-1].strip()
            if ja:
                out.append(ja)
    return out


def yj_utterances(root: Path) -> list[str]:
    path = root / "YJ_AmbigDialogue/data.txt"
    return [line.split("\t")[1] for line in path.open(encoding="utf-8") if "\t" in line]


def clean_transcript(text: str) -> str:
    """Drop J-CRe3 transcription markup: ``(F えっと)`` -> ``えっと``, ``(P)`` and ``<H>`` -> ""."""
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\([A-Z]+\)", "", text)
    return re.sub(r"\([A-Z]+ ?([^)]*)\)", r"\1", text).strip()


def jcre3_master(root: Path) -> list[str]:
    out = []
    for f in sorted((root / "J-CRe3/transcriptions").glob("*/*.txt")):
        if "-hh-" in f.name:
            continue
        for line in f.open(encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            if cols and cols[0] == "主人":
                out.append(clean_transcript(cols[-1]))
    return out


def dslc3_user_turns(root: Path) -> list[str]:
    out = []
    for f in sorted((root / "dslc3").rglob("*.log.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        out += [t["utterance"] for t in data.get("turns", []) if t.get("speaker") == "U"]
    return out


def massive_test(massive_dir: Path) -> list[str]:
    rows = massive.load(massive.download(massive_dir))
    return [r["utt"] for r in rows if r["partition"] == "test"]


# ---- candidates and build --------------------------------------------------------------------


def _row(text: str, label: list[Call], category: str, source: str) -> dict[str, Any]:
    return {
        "split": "eval",
        "spec_id": f"human.{category}",
        "category": category,
        "label": label,
        "text": text,
        "language": "ja",
        "generator": f"human:{source}",
        "prompt_version": "human-v1",
    }


def candidates(root: Path, exclude: set[str], seed: int, n_neg: dict[str, int]) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    seen = set(exclude)

    def add(text: str, label: list[Call], category: str, source: str) -> None:
        text = normalize(text).strip()
        key = dedup_key(text)
        if not text or key in seen:
            return
        seen.add(key)
        rows.append(_row(text, label, category, source))

    for source, texts in (("tatoeba", tatoeba_sentences(root)), ("jesc", jesc_sentences(root))):
        for text in texts:
            calls = parse_request(text)
            if calls is not None:
                add(text, calls, "multi_action" if len(calls) == 2 else "single", source)
            elif is_negated_request(text):
                add(text, [], "negation", source)

    pools = {
        "yj_ambig": yj_utterances(root),
        "jcre3": jcre3_master(root),
        "dslc3": dslc3_user_turns(root),
        "massive": massive_test(PROJECT_ROOT / "datasets/downloads/massive"),
    }
    for source, texts in pools.items():
        texts = [t for t in texts if 2 <= len(t) <= 60 and not ANY_GESTURE.search(t)]
        rng.shuffle(texts)
        for text in texts[: n_neg.get(source, 0)]:
            add(text, [], "no_action", source)
    return rows


def build(raw_dirs: list[Path], out_dir: Path) -> dict[str, Any]:
    rows = []
    for d in raw_dirs:
        rows += [json.loads(x) for x in (d / "train_raw.jsonl").open(encoding="utf-8")]
    stats: Counter = Counter()
    cases = []
    for r in rows:
        verified = r.get("verified")
        ok = isinstance(verified, list) and canonicalize(verified) == canonicalize(r["label"])
        stats[f"{r['category']}:{'kept' if ok else 'verifier_disagrees'}"] += 1
        if not ok:
            continue
        text = clean_transcript(r["text"]) if r["generator"] == "human:jcre3" else r["text"]
        if not text:
            continue
        digest = hashlib.sha1(text.encode()).hexdigest()[:12]
        cases.append(
            EvalCase(
                id=f"human-{digest}",
                prompt=text,
                expected=canonicalize(r["label"]),
                category=r["category"],
                language="ja",
                source=r["generator"],
            )
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    write_cases(out_dir / "eval.jsonl", cases)
    return {
        "counts": dict(Counter(c.category for c in cases)),
        "by_source": dict(Counter(c.source for c in cases)),
        "filter_stats": dict(sorted(stats.items())),
        "sha256": hashlib.sha256((out_dir / "eval.jsonl").read_bytes()).hexdigest(),
        "sources": SOURCES,
    }


def in_eval_pool(text: str, eval_keys: set[str]) -> bool:
    """Tatoeba / JESC sentences reserved for evaluation: human v1 items and a fixed 20% by hash.

    Training (hard-negative mining for v0.5) may use only sentences outside this pool, so the
    human-written evaluation keeps sources that the model has not seen.
    """
    key = dedup_key(text)
    return key in eval_keys or int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) % 5 == 0


def mining_pool(root: Path, eval_keys: set[str], seed: int, n_jesc: int) -> list[dict[str, str]]:
    """Human-written sentences for hard-negative mining (training side of the split only)."""
    rng = random.Random(seed)
    out: list[dict[str, str]] = []

    def usable(text: str) -> bool:
        return 3 <= len(text) <= 40 and parse_request(text) is None and not is_negated_request(text)

    tatoeba = [t for t in tatoeba_sentences(root) if usable(t) and not in_eval_pool(t, eval_keys)]
    jesc = [t for t in jesc_sentences(root) if usable(t) and not in_eval_pool(t, eval_keys)]
    rng.shuffle(jesc)
    rows = massive.load(massive.download(PROJECT_ROOT / "datasets/downloads/massive"))
    train_massive = [r["utt"] for r in rows if r["partition"] == "train"]
    for source, texts in (
        ("tatoeba", tatoeba),
        ("jesc", jesc[:n_jesc]),
        ("massive", train_massive),
    ):
        out += [{"text": normalize(t), "source": source} for t in texts]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates")
    c.add_argument("--root", type=Path, default=DOWNLOADS)
    c.add_argument("--out", type=Path, default=PROJECT_ROOT / "datasets/raw/human_v1")
    c.add_argument("--seed", type=int, default=20260930)
    m = sub.add_parser("pool")
    m.add_argument("--root", type=Path, default=DOWNLOADS)
    m.add_argument("--out", type=Path, default=PROJECT_ROOT / "datasets/raw/mine_pool/pool.jsonl")
    m.add_argument("--n-jesc", type=int, default=250_000)
    m.add_argument("--seed", type=int, default=20261202)
    b = sub.add_parser("build")
    b.add_argument("--raw", type=Path, nargs="+", required=True)
    b.add_argument("--out", type=Path, default=PROJECT_ROOT / "datasets/action/human_v1")
    b.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / "datasets/manifests/action_human_v1.json"
    )
    args = parser.parse_args()
    if args.cmd == "candidates":
        exclude = set()
        for split in ("train", "val", "eval"):
            path = PROJECT_ROOT / f"datasets/action/v0.4/{split}.jsonl"
            exclude |= {dedup_key(c.prompt) for c in load_cases(path)}
        n_neg = {"yj_ambig": 400, "jcre3": 300, "dslc3": 300, "massive": 200}
        rows = candidates(args.root, exclude, args.seed, n_neg)
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "train_gen.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps(Counter(f"{r['category']}:{r['generator']}" for r in rows), indent=1))
    elif args.cmd == "pool":
        eval_keys = {dedup_key(c.prompt) for c in load_cases(DEFAULT_HUMAN_EVAL)}
        rows = mining_pool(args.root, eval_keys, args.seed, args.n_jesc)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps(Counter(r["source"] for r in rows)))
    else:
        report = build(args.raw, args.out)
        args.manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps(report["counts"], indent=1))


if __name__ == "__main__":
    main()
