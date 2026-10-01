# Action schema v1（LM 側）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Action schema v1（11 の tool、任意の整数の角度、絶対と相対、LED、音量、画面の明るさ）を出力できる 3M の Action LM を作り、PC、ブラウザ、C runtime で同じ出力を出せるようにする。

**Architecture:** `jtalm.action.schema.TOOLS`（tool の表）を唯一の正とし、JSON schema、学習の target の形、grammar をすべてそこから作る。tokenizer は v1 の JSON の部品と数字 0〜9 を1 token にして作り直し、3M を最初から学習する。データは v0.5.1 を v1 の検証役で検証し直して引き継ぎ、新しい動作の文を足す。

**Tech Stack:** Python 3.13（uv）、PyTorch、SentencePiece、jsonschema、vLLM（vast.ai）、C11（runtime/host）、Emscripten（runtime/web）。

**Spec:** `docs/superpowers/specs/2026-10-02-action-schema-v1-design.md`（firmware 側の計画は `docs/superpowers/plans/2026-10-02-action-schema-v1-firmware.md`）

## Global Constraints

- 出力は動作 0〜2個の JSON 配列。`[]` は何もしない（spec 3 章）。
- tool と引数（spec 4.1）: `look` / `turn`（`direction`、`amount` か `degrees`）、`nod` / `shake`（`count` 1〜5）、`bow`（引数なし）、`set_expression`（happy / sad / surprised / neutral / angry / sleepy / doubt）、`set_led`（red / orange / yellow / green / light_blue / blue / purple / pink / white / off）、`set_volume` / `set_brightness`（`level` 0〜100）、`adjust_volume` / `adjust_brightness`（`direction` up / down、`amount` か `by` 1〜100）。
- `direction`: left / right / up / down / up_left / up_right / down_left / down_right。`look` だけ center も使える。`degrees` は 1〜180。
- `look` の center は `amount` が `normal` のときだけ許す（`degrees` は付けられない）。数値は JSON の整数で、先頭の 0 は許さない。2つの call が完全に同じ出力は許さない。
- 出力の上限は `MAX_TARGET_TOKENS = 24`（変えない）。
- 学習データの文と正解の中身は、Apache-2.0 / MIT の open model（vast.ai）とライセンスの合う既存データから作る。Claude は pipeline のコードだけを書き、文も正解も書かない（評価用の言い換えも llm-jp に書かせる）。
- 評価セットは、学習にもモデルの選択（gate の閾値、checkpoint）にも使わない。
- vast.ai は、借りる前に毎回利用者に確認し、終わったら破棄する（`jtalm.infra.job` は終了時に破棄する）。
- Python の依存は `uv add` だけで足す（`uv pip` は使わない）。
- HF の公開は同じ repo（`ayousanz/JapaneseTinyAgentLM-Action-3M`）の上書き、データは `japanese-data-analyze`。どちらも公開の直前に利用者の確認を取る。HF の repo は Discussions / PR を無効にしておく。
- 新しいソースファイルの先頭は `# SPDX-License-Identifier: Apache-2.0` と `# Copyright 2026 ayutaz`（C は `//` か `/* */`）。
- lint: `uv run --only-dev ruff check src tests firmware/tools` と `uv run --only-dev ruff format --check src tests firmware/tools` が通ること。

## Review Focus

1. **数字の表記ゆれ（「四十五度」「４５度」「45°」「45%」）:** どれも同じ値になると利用者は期待する。Task 8 の spec で表記ごとに文を作らせ、Task 13 の評価で表記ごとの正解率を出す。
2. **数値の桁で確信度が割れ、gate で止まる:** 「右に45度」が gate で `[]` になると、v0 と同じ不満が残る。Task 13 で、数値を含む正解の文だけの「gate で止まった率」を別に出し、完了の条件に入れる。
3. **部屋の照明・エアコンの温度・テレビの音量:** `set_led` / `set_volume` と取り違えると誤って動く。Task 8 の no_action の spec と、Task 10 の実例セットの紛らわしい文（誤動作 0 件が条件）で確かめる。
4. **範囲外の値（「音量を150にして」「明るさを200%に」）:** 利用者は最大値になると期待する。grammar は範囲外を出せないので、正解を上限（100）にした spec を Task 8 で足し、Task 13 で確かめる。
5. **「もう少し右」と「右に45度」の取り違え（`turn` と `look`）:** 相対と絶対を取り違えると、首が想定外の位置へ行く。Task 8 の spec の規則と、Task 13 の look / turn 別の集計で確かめる。

## 2つの計画をまたぐ実行の順番

firmware は `runtime/host/grammar.c` をそのまま build するので、この計画の Task 6（C の grammar を v1 にする）の後は、firmware に v1 の `.jtlm` が要る（v0 の `.jtlm` では起動時に LM が止まる）。そのため、次の順に進める。

1. LM の Task 0〜5 と、firmware の Task 1（F1: LED）、Task 2（F2: 可動域）、Task 3（PC での照合の仕組み）。firmware の3つは v0 の grammar のまま実機で行う。F1 で LED が点かなければ、そこで止めて利用者と相談する。
2. LM の Task 6〜12（C の grammar、データ、tokenizer v1）と、firmware の Task 4（検査と計画を v1 に。PC だけで確かめる。LM の Task 4 の `plan_v1` が要る）。
3. LM の Task 13（学習と評価）。
4. firmware の Task 5〜8（実機で v1 の動作。Task 13 で選んだモデルの `.jtlm` を書く）と、LM の Task 14、15。

## ファイルの構成

| ファイル | 役割 |
|---|---|
| `src/jtalm/action/schema.py` | v1 の tool の表 `TOOLS`、JSON schema の生成、検証、canonicalize、`uses_v1_only` |
| `src/jtalm/action/action_schema_v1.json`（新規、生成物） | `python -m jtalm.action.schema` が書く JSON schema。vLLM の guided decoding と配布に使う |
| `src/jtalm/action/mapping.py` | v0 の対応表に加え、`Limits` と `plan_v1`（firmware の dispatcher の基準） |
| `src/jtalm/model/format.py` | `TOOLS` から JSON の部品、引数の順、全 call の部品列を作る |
| `src/jtalm/model/grammar.py` | 全 call の部品列の trie で、次に許す token を決める |
| `runtime/host/grammar.c`、`jtalm.h`、`model.c`、`main.c` | 同じ grammar の C 版と、検査用の `--grammar-trace` |
| `src/jtalm/model/hf_inference.py` | HF 用の単体の推論スクリプト（grammar の複製を v1 に） |
| `src/jtalm/eval/metrics.py` | 逆方向の判定を斜めと adjust に広げ、数値の誤差を集計 |
| `src/jtalm/data/specs_v1.py`（新規） | v1 の新しい動作の spec |
| `src/jtalm/data/prompts.py` | ロボットの説明、文の条件、検証役の prompt を v1 に |
| `src/jtalm/data/generate.py` | spec_set `v1` / `v1_paraphrase`、phase `reverify` |
| `src/jtalm/data/massive.py` | 音量の intent を `[]` の候補から外す |
| `src/jtalm/data/build_v1.py`（新規） | 引き継ぎ、付け直し、新しい文、eval v3、評価セットの付け直しをまとめる |
| `src/jtalm/data/stackchan_eval.py`（新規） | スタックチャン実例セットの組み立てと、確認用の表 |
| `src/jtalm/infra/jobs.py` | v1 のデータ生成と学習の job |
| `src/jtalm/model/eval_suite.py`、`release.py`、`model_card_action.md` | 評価セット、配布物、モデルカードを v1 に |
| `runtime/web/index.html` | 表示を v1 に |

---

### Task 0: v0 の基準点に tag を付ける

v1 の変更で v0 の grammar と tokenizer はコードから消える。v0 の結果を再現できるように、main の最新 commit に tag を付ける。

**Files:** なし（git の tag だけ）

- [ ] **Step 1: tag を付ける**

```bash
git tag -a action-v0.5.1 a803813 -m "Action LM v0.5.1 (schema v0), the version before schema v1"
git tag -l action-v0.5.1
```

Expected: `action-v0.5.1`

（push は利用者が指示したときだけ行う。）

---

### Task 1: schema v1（tool の表、JSON schema、検証）

**Files:**
- Modify: `src/jtalm/action/schema.py`（全体を書き換え）
- Modify: `src/jtalm/action/__init__.py`
- Create: `src/jtalm/action/action_schema_v1.json`（Step 5 で生成）
- Modify: `tests/test_action_schema.py`

**Interfaces:**
- Produces:
  - `Arg(name: str, values: tuple[str, ...] = (), range: tuple[int, int] | None = None)`、`Tool(first: Arg | None = None, second: tuple[Arg, ...] = ())`
  - `TOOLS: dict[str, Tool]`（順序は spec 4.1 の表の順）、`TOOL_NAMES`、`DIRECTIONS`（9個、最後が center）、`TURN_DIRECTIONS`（8個）、`AMOUNTS`、`EXPRESSIONS`（7個）、`COLORS`（10個）、`ADJUST_DIRECTIONS`、`DEGREES = (1, 180)`、`LEVEL = (0, 100)`、`BY = (1, 100)`、`COUNT = (1, 5)`、`MAX_CALLS = 2`
  - `build_schema() -> dict`、`load_schema() -> dict`、`validate(calls) -> list[str]`、`parse_output(raw) -> ParsedOutput`、`canonicalize(calls) -> list[Call]`、`to_json(calls) -> str`、`uses_v1_only(calls: list[Call]) -> bool`

- [ ] **Step 1: 失敗する test を書く**

`tests/test_action_schema.py` の `test_invalid_outputs` の `count range` の行を `count 6` に直し（v1 では 4 が正しい）、次の test を足す。

```python
from jtalm.action.schema import TOOLS, build_schema, load_schema, uses_v1_only


def call(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


@pytest.mark.parametrize(
    "calls",
    [
        [call("look", direction="right", degrees=45)],
        [call("look", direction="up_left", amount="slight")],
        [call("turn", direction="down_right", degrees=180)],
        [call("nod", count=5), call("shake", count=1)],
        [call("bow")],
        [call("set_expression", expression="doubt")],
        [call("set_led", color="light_blue"), call("set_led", color="off")],
        [call("set_volume", level=0), call("set_brightness", level=100)],
        [call("adjust_volume", direction="up", by=10)],
        [call("adjust_brightness", direction="down", amount="large")],
    ],
)
def test_v1_valid_outputs(calls: list) -> None:
    assert validate(calls) == []


@pytest.mark.parametrize(
    ("calls", "reason"),
    [
        ([call("look", direction="right", degrees=0)], "degrees below 1"),
        ([call("look", direction="right", degrees=181)], "degrees above 180"),
        ([call("look", direction="right", amount="normal", degrees=45)], "both magnitudes"),
        ([call("turn", direction="center", amount="normal")], "turn has no center"),
        ([call("look", direction="center", degrees=10)], "center takes no degrees"),
        ([call("nod", count=6)], "count above 5"),
        ([call("bow", count=1)], "bow takes no arguments"),
        ([call("set_led", color="black")], "color enum"),
        ([call("set_volume", level=101)], "level above 100"),
        ([call("adjust_volume", direction="left", by=10)], "adjust direction"),
        ([call("adjust_volume", direction="up", by=0)], "by below 1"),
        ([call("adjust_volume", direction="up")], "missing amount or by"),
    ],
)
def test_v1_invalid_outputs(calls: list, reason: str) -> None:
    assert validate(calls) != [], reason


def test_schema_file_is_generated_from_tools() -> None:
    assert load_schema() == build_schema()
    assert list(TOOLS) == ["look", "turn", "nod", "shake", "bow", "set_expression", "set_led",
                           "set_volume", "adjust_volume", "set_brightness", "adjust_brightness"]


def test_uses_v1_only_separates_v0_outputs() -> None:
    assert not uses_v1_only([look("right", "large"), call("nod", count=3)])
    assert not uses_v1_only([call("set_expression", expression="neutral")])
    assert uses_v1_only([call("look", direction="right", degrees=90)])
    assert uses_v1_only([call("look", direction="up_left", amount="normal")])
    assert uses_v1_only([call("nod", count=4)])
    assert uses_v1_only([call("set_expression", expression="angry")])
    assert uses_v1_only([call("turn", direction="right", amount="slight")])
    assert uses_v1_only([call("set_volume", level=50)])
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_action_schema.py -q`
Expected: FAIL（`ImportError: cannot import name 'TOOLS'`）

- [ ] **Step 3: `schema.py` を書き換える**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Action schema v1: the tool table, parsing, validation, and canonicalization of model outputs.

An Action LM output is a JSON array of 0-2 calls such as
``[{"name": "look", "arguments": {"direction": "right", "degrees": 45}}]``.
``[]`` means no-action. ``TOOLS`` is the single source of truth: the JSON schema file, the
training target format, and the decoding grammar are all derived from it
(docs/superpowers/specs/2026-10-02-action-schema-v1-design.md).
"""

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

Call = dict[str, Any]

DIRECTIONS = ("left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right",
              "center")  # fmt: skip
TURN_DIRECTIONS = DIRECTIONS[:-1]
AMOUNTS = ("slight", "normal", "large")
EXPRESSIONS = ("happy", "sad", "surprised", "neutral", "angry", "sleepy", "doubt")
COLORS = ("red", "orange", "yellow", "green", "light_blue", "blue", "purple", "pink", "white",
          "off")  # fmt: skip
ADJUST_DIRECTIONS = ("up", "down")
DEGREES = (1, 180)
LEVEL = (0, 100)
BY = (1, 100)
COUNT = (1, 5)
MAX_CALLS = 2
SCHEMA_FILE = "action_schema_v1.json"


@dataclass(frozen=True)
class Arg:
    """One argument: an enum (``values``) or an inclusive integer ``range``."""

    name: str
    values: tuple[str, ...] = ()
    range: tuple[int, int] | None = None


@dataclass(frozen=True)
class Tool:
    """``first`` is the first argument (None: no arguments); exactly one of ``second`` follows."""

    first: Arg | None = None
    second: tuple[Arg, ...] = ()


_MAGNITUDE = (Arg("amount", AMOUNTS), Arg("degrees", range=DEGREES))
_ADJUST = (Arg("amount", AMOUNTS), Arg("by", range=BY))
TOOLS: dict[str, Tool] = {
    "look": Tool(Arg("direction", DIRECTIONS), _MAGNITUDE),
    "turn": Tool(Arg("direction", TURN_DIRECTIONS), _MAGNITUDE),
    "nod": Tool(Arg("count", range=COUNT)),
    "shake": Tool(Arg("count", range=COUNT)),
    "bow": Tool(),
    "set_expression": Tool(Arg("expression", EXPRESSIONS)),
    "set_led": Tool(Arg("color", COLORS)),
    "set_volume": Tool(Arg("level", range=LEVEL)),
    "adjust_volume": Tool(Arg("direction", ADJUST_DIRECTIONS), _ADJUST),
    "set_brightness": Tool(Arg("level", range=LEVEL)),
    "adjust_brightness": Tool(Arg("direction", ADJUST_DIRECTIONS), _ADJUST),
}
TOOL_NAMES = tuple(TOOLS)

# The v0 subset, for telling v0 labels from labels that need schema v1 (jtalm.data.build_v1).
_V0_DIRECTIONS = ("left", "right", "up", "down", "center")
_V0_EXPRESSIONS = ("happy", "sad", "surprised", "neutral")


def _arg_schema(arg: Arg) -> dict[str, Any]:
    if arg.values:
        return {"enum": list(arg.values)}
    assert arg.range is not None
    return {"type": "integer", "minimum": arg.range[0], "maximum": arg.range[1]}


def _call_schema(name: str, props: dict[str, Any]) -> dict[str, Any]:
    arguments = {"type": "object", "additionalProperties": False, "required": list(props),
                 "properties": props}  # fmt: skip
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "arguments"],
        "properties": {"name": {"const": name}, "arguments": arguments},
    }


def build_schema() -> dict[str, Any]:
    """The JSON schema of ``TOOLS`` (one ``oneOf`` item per tool and second-argument choice)."""
    items = []
    for name, tool in TOOLS.items():
        if tool.first is None:
            items.append(_call_schema(name, {}))
            continue
        first = {tool.first.name: _arg_schema(tool.first)}
        if not tool.second:
            items.append(_call_schema(name, first))
        for second in tool.second:
            items.append(_call_schema(name, {**first, second.name: _arg_schema(second)}))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/ayutaz/JapaneseTinyAgentLM/{SCHEMA_FILE}",
        "title": "JapaneseTinyAgentLM Action schema v1",
        "type": "array",
        "maxItems": MAX_CALLS,
        "items": {"oneOf": items},
    }


@cache
def load_schema() -> dict[str, Any]:
    text = resources.files("jtalm.action").joinpath(SCHEMA_FILE).read_text("utf-8")
    return json.loads(text)


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


@dataclass(frozen=True)
class ParsedOutput:
    """Result of parsing raw model text. ``calls`` is None when the text is not a JSON array."""

    raw: str
    calls: list[Call] | None
    errors: tuple[str, ...] = field(default=())

    @property
    def json_valid(self) -> bool:
        return self.calls is not None

    @property
    def schema_valid(self) -> bool:
        return self.calls is not None and not self.errors


def validate(calls: Any) -> list[str]:
    """Return schema violations plus project rules. Empty means valid.

    Project rules: no duplicate calls, and ``look`` toward center takes ``amount`` only.
    """
    errors = [e.message for e in _validator().iter_errors(calls)]
    if isinstance(calls, list):
        seen: set[str] = set()
        for call in calls:
            key = json.dumps(call, sort_keys=True, ensure_ascii=False)
            if key in seen:
                errors.append(f"duplicate call: {key}")
            seen.add(key)
            if (
                isinstance(call, dict)
                and call.get("name") == "look"
                and isinstance(call.get("arguments"), dict)
                and call["arguments"].get("direction") == "center"
                and "degrees" in call["arguments"]
            ):
                errors.append("look toward center takes no degrees")
    return errors


def parse_output(raw: str) -> ParsedOutput:
    """Parse raw model text into calls and validate them."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ParsedOutput(raw=raw, calls=None, errors=("not valid JSON",))
    if not isinstance(value, list):
        return ParsedOutput(raw=raw, calls=None, errors=("top level is not a JSON array",))
    return ParsedOutput(raw=raw, calls=value, errors=tuple(validate(value)))


def canonicalize(calls: list[Call]) -> list[Call]:
    """Normalize calls for comparison. Order is kept because it is part of the meaning.

    ``look`` with ``direction == "center"`` ignores ``amount``, so it is normalized to ``normal``.
    """
    canonical: list[Call] = []
    for call in calls:
        args = dict(call.get("arguments", {}))
        if call.get("name") == "look" and args.get("direction") == "center" and "amount" in args:
            args["amount"] = "normal"
        canonical.append({"name": call.get("name"), "arguments": args})
    return canonical


def to_json(calls: list[Call]) -> str:
    """Serialize calls in the compact canonical form (sorted keys) used for comparison and records.

    Training targets use ``jtalm.model.format.target_json`` (name first), which parses the same.
    """
    return json.dumps(
        canonicalize(calls), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def uses_v1_only(calls: list[Call]) -> bool:
    """True when some call cannot be written in schema v0 (a new tool, value, or argument)."""
    for call in calls:
        name, args = call["name"], call["arguments"]
        if name not in ("look", "set_expression", "nod"):
            return True
        if name == "look" and ("degrees" in args or args["direction"] not in _V0_DIRECTIONS):
            return True
        if name == "set_expression" and args["expression"] not in _V0_EXPRESSIONS:
            return True
        if name == "nod" and int(args["count"]) > 3:
            return True
    return False


def main() -> None:
    """Write the JSON schema file from ``TOOLS`` (run after changing the table)."""
    path = Path(__file__).with_name(SCHEMA_FILE)
    path.write_text(json.dumps(build_schema(), indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
```

`src/jtalm/action/__init__.py` の docstring を `"""Action schema v1 and the category-to-servo mapping for the K151."""` にし、import と `__all__` に `ADJUST_DIRECTIONS`、`COLORS`、`TOOLS`、`TURN_DIRECTIONS`、`Arg`、`Tool`、`build_schema`、`uses_v1_only` を足す。

- [ ] **Step 4: JSON schema の file を生成する**

Run: `uv run python -m jtalm.action.schema`
Expected: `...\src\jtalm\action\action_schema_v1.json` と表示され、file ができる。

- [ ] **Step 5: test が通ることを確かめる**

Run: `uv run pytest tests/test_action_schema.py -q`
Expected: PASS（`test_bench_expected_outputs_are_valid` も、v0 の出力は v1 でも正しいので通る）

- [ ] **Step 6: Commit**

```bash
git add src/jtalm/action/schema.py src/jtalm/action/__init__.py src/jtalm/action/action_schema_v1.json tests/test_action_schema.py
git commit -m "Action schema v1: tool table (look/turn with amount or degrees, diagonals, nod/shake 1-5, bow, 7 expressions, set_led, set/adjust volume and brightness) and the generated JSON schema"
```

---

### Task 2: 学習の target の形と JSON の部品（format.py）

**Files:**
- Modify: `src/jtalm/model/format.py`
- Modify: `src/jtalm/model/data.py:18`（コメントだけ）
- Modify: `tests/test_model.py`

**Interfaces:**
- Consumes: `TOOLS`、`Arg`（Task 1）
- Produces:
  - `head_piece(name: str) -> str`、`key_piece(arg: Arg) -> str`、`close_piece(arg: Arg) -> str`
  - `all_call_pieces() -> list[tuple[str, ...]]`（すべての正しい call を、1 token ずつの部品の列で。順序は `TOOLS` の順）
  - `JSON_PIECES: tuple[str, ...]`、`ENUM_VALUES: tuple[str, ...]`（列挙値と数字 `0`〜`9`）、`DIGITS`
  - `target_json(calls) -> str`（v0 と同じ関数名と役割）

- [ ] **Step 1: 失敗する test を書く**

`tests/test_model.py` に足す。

```python
from jtalm.model.format import ENUM_VALUES, JSON_PIECES, all_call_pieces  # noqa: E402

V1_TARGETS = [
    [{"name": "look", "arguments": {"direction": "right", "degrees": 45}}],
    [{"name": "turn", "arguments": {"direction": "up_left", "degrees": 180}},
     {"name": "adjust_volume", "arguments": {"direction": "down", "by": 100}}],
    [{"name": "bow", "arguments": {}}, {"name": "set_led", "arguments": {"color": "light_blue"}}],
    [{"name": "set_volume", "arguments": {"level": 0}}],
]  # fmt: skip


def test_every_call_piece_sequence_is_its_target_json() -> None:
    calls = all_call_pieces()
    assert len(calls) == len(set(calls))
    for pieces in calls:
        text = "[" + "".join(pieces) + "]"
        parsed = parse_output(text)
        assert parsed.schema_valid, text
        assert target_json(parsed.calls) == text


def test_v1_targets_keep_pieces_whole_and_fit_the_target_limit(tmp_path: Path) -> None:
    lines = [target_json(c) for c in V1_TARGETS] * 20 + ["右を向いて", "音量を上げて"] * 20
    sp = tokenizer.train(lines, 400, tmp_path / "v1").as_posix()
    codec = Codec(sp)
    for piece in (*JSON_PIECES, *ENUM_VALUES):
        assert len(codec.sp.encode(piece)) == 1, piece
    longest = target_json(V1_TARGETS[1])
    assert codec.sp.decode(codec.sp.encode(longest)) == longest
    assert len(codec.sp.encode(longest)) + 1 <= 24  # + </s>
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run --group train pytest tests/test_model.py -q`
Expected: FAIL（`ImportError: cannot import name 'all_call_pieces'`）

- [ ] **Step 3: `format.py` を書き換える**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Sequence format shared by the tokenizer, training, and decoding.

One example is ``<s> <act> prompt <out> target </s>`` and the loss covers ``target </s>`` only.

The target is the compact JSON of the canonicalized calls with ``name`` first and the arguments in
schema order, e.g. ``[{"name":"look","arguments":{"direction":"right","degrees":45}}]``.
This differs from ``jtalm.action.schema.to_json`` (sorted keys, used for comparison) so that the
model decides the tool before its arguments. Both parse to the same calls.

Every target is a sequence of fixed pieces, each one SentencePiece token (user-defined symbols):
the head of a call (its name and first key), a key between two arguments, a closer, an enum
value, or one digit of a number. A ``look`` call with 45 degrees is
``{"name":"look","arguments":{"direction":"`` ``right`` ``","degrees":`` ``4`` ``5`` ``}}``.
"""

import json

from jtalm.action.schema import TOOLS, Arg, Call, canonicalize

ACT = "<act>"
OUT = "<out>"
DIGITS = tuple("0123456789")
ARG_ORDER = {
    name: tuple(a.name for a in (tool.first, *tool.second) if a is not None)
    for name, tool in TOOLS.items()
}


def _quote(arg: Arg) -> str:
    return '"' if arg.values else ""


def head_piece(name: str) -> str:
    """The call up to its first value: ``{"name":"nod","arguments":{"count":``."""
    first = TOOLS[name].first
    if first is None:
        return f'{{"name":"{name}","arguments":{{}}}}'  # a whole call (bow)
    return f'{{"name":"{name}","arguments":{{"{first.name}":{_quote(first)}'


def key_piece(arg: Arg) -> str:
    """Between the (string) first value and ``arg``: ``","degrees":``."""
    return f'","{arg.name}":{_quote(arg)}'


def close_piece(arg: Arg) -> str:
    return '"}}' if arg.values else "}}"


def _options(arg: Arg) -> list[tuple[str, ...]]:
    if arg.values:
        return [(v,) for v in arg.values]
    assert arg.range is not None
    return [tuple(str(n)) for n in range(arg.range[0], arg.range[1] + 1)]


def all_call_pieces() -> list[tuple[str, ...]]:
    """Every valid call as its piece sequence (``look`` center takes only amount normal)."""
    calls: list[tuple[str, ...]] = []
    for name, tool in TOOLS.items():
        head = head_piece(name)
        if tool.first is None:
            calls.append((head,))
            continue
        for value in _options(tool.first):
            if not tool.second:
                calls.append((head, *value, close_piece(tool.first)))
                continue
            assert tool.first.values, "a second argument follows a string value"
            for second in tool.second:
                options = _options(second)
                if name == "look" and value == ("center",):
                    if second.name != "amount":
                        continue
                    options = [("normal",)]
                for w in options:
                    calls.append((head, *value, key_piece(second), *w, close_piece(second)))
    return calls


def _unique(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


JSON_PIECES = _unique(
    ["[]", "[", "]", ","]
    + [head_piece(n) for n in TOOLS]
    + [key_piece(a) for t in TOOLS.values() for a in t.second]
    + ['"}}', "}}"]
)
ENUM_VALUES = _unique(
    [v for t in TOOLS.values() for a in (t.first, *t.second) if a is not None for v in a.values]
    + list(DIGITS)
)


def target_json(calls: list[Call]) -> str:
    ordered = []
    for call in canonicalize(calls):
        args = call["arguments"]
        keys = ARG_ORDER.get(call["name"], ())
        arguments = {k: args[k] for k in keys if k in args}
        arguments.update({k: v for k, v in sorted(args.items()) if k not in arguments})
        ordered.append({"name": call["name"], "arguments": arguments})
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
```

`src/jtalm/model/data.py:18` のコメントを `# longest v1 target is 18 tokens + </s> (two calls with 3-digit numbers)` にする。

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run --group train pytest tests/test_model.py -q`
Expected: PASS。`test_tokenizer_keeps_json_fragments_whole` の `len(...) == 7` も v1 で変わらない（`look` の amount 指定は 7 token のまま）。

- [ ] **Step 5: Commit**

```bash
git add src/jtalm/model/format.py src/jtalm/model/data.py tests/test_model.py
git commit -m "format: derive the target pieces from the v1 tool table; digits 0-9 are single tokens"
```

---

### Task 3: Python の grammar（trie）

**Files:**
- Modify: `src/jtalm/model/grammar.py`（全体を書き換え）
- Create: `tests/test_grammar_v1.py`

**Interfaces:**
- Consumes: `all_call_pieces()`（Task 2）、`Codec`（`jtalm.model.data`）
- Produces: `ActionGrammar(codec)` と `ActionGrammar.allowed(generated: list[int]) -> list[int]`（v0 と同じ名前と使い方。戻り値は **token id の昇順**）、`ActionGrammar.id: dict[str, int]`（部品 → id）

- [ ] **Step 1: 失敗する test を書く**

`tests/test_grammar_v1.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import random
from pathlib import Path

import pytest

pytest.importorskip("sentencepiece")

from jtalm.action.schema import parse_output  # noqa: E402
from jtalm.model import tokenizer  # noqa: E402
from jtalm.model.data import Codec  # noqa: E402
from jtalm.model.format import all_call_pieces, target_json  # noqa: E402
from jtalm.model.grammar import ActionGrammar  # noqa: E402

SAMPLE = [[{"name": "look", "arguments": {"direction": "right", "degrees": 45}}],
          [{"name": "bow", "arguments": {}}], []]  # fmt: skip


@pytest.fixture(scope="module")
def grammar(tmp_path_factory: pytest.TempPathFactory) -> ActionGrammar:
    lines = [target_json(c) for c in SAMPLE] * 20 + ["右を向いて", "こんにちは"] * 20
    return ActionGrammar(Codec(tokenizer.train(lines, 400, tmp_path_factory.mktemp("g") / "t")))


def walk(g: ActionGrammar, rng: random.Random) -> list[int]:
    ids: list[int] = []
    while True:
        options = g.allowed(ids)
        assert options, f"dead end after {ids}"
        assert options == sorted(options)
        nxt = rng.choice(options)
        if nxt == g.eos:
            return ids
        ids.append(nxt)


def test_random_walks_always_parse_and_never_duplicate(grammar: ActionGrammar) -> None:
    rng = random.Random(0)
    sp = grammar.codec.sp
    for _ in range(3000):
        text = sp.decode(walk(grammar, rng))
        parsed = parse_output(text)
        assert parsed.schema_valid, (text, parsed.errors)


def test_every_single_call_is_reachable(grammar: ActionGrammar) -> None:
    for pieces in all_call_pieces():
        ids = [grammar.id["["]]
        for piece in pieces:
            assert grammar.id[piece] in grammar.allowed(ids), pieces
            ids.append(grammar.id[piece])
        assert grammar.id["]"] in grammar.allowed(ids)


@pytest.mark.parametrize("pieces", [
    ('{"name":"bow","arguments":{}}',),
    ('{"name":"look","arguments":{"direction":"', "center", '","amount":"', "normal", '"}}'),
    ('{"name":"look","arguments":{"direction":"', "right", '","degrees":', "4", "5", "}}"),
    ('{"name":"set_volume","arguments":{"level":', "1", "0", "0", "}}"),
    ('{"name":"set_volume","arguments":{"level":', "0", "}}"),
    ('{"name":"nod","arguments":{"count":', "5", "}}"),
])  # fmt: skip
def test_second_call_cannot_repeat_the_first(grammar: ActionGrammar, pieces: tuple) -> None:
    ids = [grammar.id["["], *(grammar.id[p] for p in pieces), grammar.id[","]]
    for piece in pieces:
        options = grammar.allowed(ids)
        if grammar.id[piece] not in options:
            return  # the duplicate path was cut before its end
        ids.append(grammar.id[piece])
    pytest.fail(f"the grammar allowed a duplicate of {pieces}")


def test_numbers_have_no_leading_zero_and_stay_in_range(grammar: ActionGrammar) -> None:
    head = grammar.id['{"name":"look","arguments":{"direction":"']
    ids = [grammar.id["["], head, grammar.id["right"], grammar.id['","degrees":']]
    assert grammar.id["0"] not in grammar.allowed(ids)  # degrees start at 1
    ids += [grammar.id["1"], grammar.id["8"]]
    assert grammar.allowed(ids) == sorted([grammar.id["0"], grammar.id["}}"]])  # 180 or 18
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run --group train pytest tests/test_grammar_v1.py -q`
Expected: FAIL（v0 の grammar には `codec` 属性も v1 の部品もない）

- [ ] **Step 3: `grammar.py` を書き換える**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Grammar-constrained decoding for Action schema v1.

Every target token is one fixed piece (``jtalm.model.format``), so the grammar is

    [] </s>
    [ CALL ] </s>
    [ CALL , CALL ] </s>        (the second call must differ from the first)

where CALL is any piece sequence of ``all_call_pieces()``: a call head, the first value, then for
look / turn / adjust_* a key and the second value, then a closer. Numbers are one token per digit
with no leading zero and stay inside the argument's range.

The calls form a trie that counts, for every prefix, how many complete calls lie below each next
piece. A piece is allowed when at least one of those calls differs from the first call, so the
grammar never reaches a dead end and never lets a duplicate through. Any output decoded under
this grammar parses, passes the schema, and has no duplicate call. The allowed ids are returned
in ascending order so that ties resolve like the C runtime (lowest id).
"""

from collections import defaultdict

from jtalm.model.data import Codec
from jtalm.model.format import all_call_pieces


class ActionGrammar:
    def __init__(self, codec: Codec) -> None:
        sp = codec.sp
        self.codec = codec
        self.eos = codec.eos

        def tid(piece: str) -> int:
            ids = sp.encode(piece)
            if len(ids) != 1:
                raise ValueError(f"{piece!r} is not a single token in {codec.path.name}")
            return ids[0]

        calls = all_call_pieces()
        pieces = {"[]", "[", "]", ","} | {p for c in calls for p in c}
        self.id = {p: tid(p) for p in sorted(pieces)}
        self.piece = {i: p for p, i in self.id.items()}
        self._complete = set(calls)
        self._below: dict[tuple[str, ...], dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for c in calls:
            for k in range(len(c)):
                self._below[c[:k]][c[k]] += 1

    def _parse(self, generated: list[int]) -> tuple[str, list[tuple[str, ...]], tuple[str, ...]]:
        """Outer step, completed calls, and the pieces of the call being built."""
        step, calls, current = "start", [], ()
        for token in generated:
            piece = self.piece.get(token)
            if step == "start":
                step = "empty" if piece == "[]" else "call"
            elif step == "call":
                current = (*current, piece)
                if current in self._complete:
                    calls.append(current)
                    current = ()
                    step = "after_call"
            elif step == "after_call":
                step = "call" if piece == "," else "end"
            else:  # empty / end
                step = "done"
        return step, calls, current

    def allowed(self, generated: list[int]) -> list[int]:
        """Token ids allowed after ``generated`` (the target tokens produced so far), ascending."""
        step, calls, current = self._parse(generated)
        if step == "start":
            return sorted([self.id["[]"], self.id["["]])
        if step == "call":
            first = calls[0] if calls else None
            out = []
            for piece, n in self._below[current].items():
                if first is not None and first[: len(current) + 1] == (*current, piece):
                    n -= 1  # the first call itself is one of the calls below this piece
                if n > 0:
                    out.append(self.id[piece])
            return sorted(out)
        if step == "after_call":
            return sorted([self.id[","], self.id["]"]]) if len(calls) == 1 else [self.id["]"]]
        return [self.eos]  # "empty" / "end" / "done"
```

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run --group train pytest tests/test_grammar_v1.py tests/test_model.py -q`
Expected: PASS

- [ ] **Step 5: 既存の test を v1 に合わせる**

Run: `uv run --group train pytest -q`
Expected: `tests/test_export.py::test_c_runtime_matches_python` の `--grammar` が FAIL する（C の grammar がまだ v0）。それ以外が通ることを確かめる。ほかに失敗する test があれば、v0 の値を前提にしている箇所を v1 の値に直す（例: `ActionGrammar` の部品の数）。`test_c_runtime_matches_python` は Task 6 で通す。

- [ ] **Step 6: Commit**

```bash
git add src/jtalm/model/grammar.py tests/test_grammar_v1.py
git commit -m "grammar: schema v1 as a trie over every call (digits with range and no leading zero; duplicates cut without dead ends)"
```

---

### Task 4: `plan_v1`（firmware の dispatcher の基準）

**Files:**
- Modify: `src/jtalm/action/mapping.py`（末尾に追記。v0 の関数は残す）
- Modify: `tests/test_mapping.py`

**Interfaces:**
- Consumes: `Call`（Task 1）、`nod_targets`、`YAW_DEG`、`PITCH_DEG`（既存）
- Produces（firmware 側の計画が使う。名前と形を変えないこと）:

```python
@dataclass(frozen=True)
class Limits:
    yaw_min: float = -45; yaw_max: float = 45; pitch_min: float = -10; pitch_max: float = 85
DEFAULT_LIMITS = Limits()
SHAKE_YAW_DEG = 15; BOW_HOLD_MS = 500
ADJUST_STEP = {"slight": 10, "normal": 20, "large": 30}; BRIGHTNESS_MIN = 5
def plan_v1(calls: list[dict], start: tuple[float, float], limits: Limits = DEFAULT_LIMITS) -> list[dict]
```

steps は次のどれか。
- `{"kind": "move", "yaw": float, "pitch": float, "clamped": bool}`
- `{"kind": "pause", "ms": int}`
- `{"kind": "expr", "expression": str}`
- `{"kind": "led", "color": str}`
- `{"kind": "volume", "level": int}` / `{"kind": "volume", "delta": int}`
- `{"kind": "brightness", "level": int}` / `{"kind": "brightness", "delta": int}`

- [ ] **Step 1: 失敗する test を書く**

`tests/test_mapping.py` に足す。

```python
from jtalm.action.mapping import BOW_HOLD_MS, DEFAULT_LIMITS, Limits, plan_v1


def c(name: str, **arguments: object) -> dict:
    return {"name": name, "arguments": arguments}


def moves(steps: list[dict]) -> list[tuple[float, float]]:
    return [(s["yaw"], s["pitch"]) for s in steps if s["kind"] == "move"]


def test_look_degrees_is_absolute_and_clamped() -> None:
    steps = plan_v1([c("look", direction="up", degrees=90)], start=(10, 0))
    assert steps == [{"kind": "move", "yaw": 10, "pitch": 85, "clamped": True}]
    steps = plan_v1([c("look", direction="right", degrees=45)], start=(-20, 5))
    assert steps == [{"kind": "move", "yaw": 45, "pitch": 5, "clamped": False}]


def test_look_amount_keeps_the_v0_angles_and_diagonals_move_both_axes() -> None:
    assert moves(plan_v1([c("look", direction="right", amount="normal")], (0, 7))) == [(20, 7)]
    assert moves(plan_v1([c("look", direction="up_left", amount="large")], (0, 0))) == [(-30, 15)]
    assert moves(plan_v1([c("look", direction="center", amount="normal")], (30, 9))) == [(0, 0)]


def test_turn_is_relative_to_the_current_pose_and_carries_between_calls() -> None:
    calls = [c("turn", direction="right", amount="slight"), c("turn", direction="right", degrees=30)]
    assert moves(plan_v1(calls, start=(10, 0))) == [(20, 0), (45, 0)]  # 50 clamped to 45


def test_shake_bow_and_nod() -> None:
    assert moves(plan_v1([c("shake", count=2)], (40, 0))) == [(45, 0), (25, 0), (45, 0), (25, 0),
                                                            (40, 0)]  # fmt: skip
    bow = plan_v1([c("bow")], (0, 10))
    assert moves(bow) == [(0, -10), (0, 10)]
    assert {"kind": "pause", "ms": BOW_HOLD_MS} in bow
    assert moves(plan_v1([c("nod", count=1)], (0, 0))) == [(0, -10), (0, 4), (0, 0)]
    # the final return is added only when the last target differs from the start (v0 firmware)
    assert moves(plan_v1([c("nod", count=1)], (0, 10))) == [(0, -4), (0, 10)]


def test_state_steps() -> None:
    steps = plan_v1([c("set_led", color="blue"), c("adjust_volume", direction="down", amount="large")],
                    (0, 0))  # fmt: skip
    assert steps == [{"kind": "led", "color": "blue"}, {"kind": "volume", "delta": -30}]
    assert plan_v1([c("set_brightness", level=0)], (0, 0)) == [{"kind": "brightness", "level": 0}]
    assert plan_v1([c("adjust_brightness", direction="up", by=15)], (0, 0)) == [
        {"kind": "brightness", "delta": 15}]
    assert plan_v1([c("set_expression", expression="doubt")], (0, 0)) == [
        {"kind": "expr", "expression": "doubt"}]


def test_default_limits_match_the_spec_target() -> None:
    assert DEFAULT_LIMITS == Limits(-45, 45, -10, 85)
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_mapping.py -q`
Expected: FAIL（`ImportError: cannot import name 'plan_v1'`）

- [ ] **Step 3: `mapping.py` に追記する**

```python
# -- schema v1 (docs/superpowers/specs/2026-10-02-action-schema-v1-design.md, section 6) --------


@dataclass(frozen=True)
class Limits:
    """Soft limits of the head in degrees (yaw positive right, pitch positive up)."""

    yaw_min: float = -45
    yaw_max: float = 45
    pitch_min: float = -10
    pitch_max: float = 85


DEFAULT_LIMITS = Limits()  # the spec's target; the final values are set on the device (F2)
SHAKE_YAW_DEG = 15
BOW_HOLD_MS = 500
ADJUST_STEP = {"slight": 10, "normal": 20, "large": 30}
BRIGHTNESS_MIN = 5  # the firmware floor; level 0 would hide the face

_YAW_SIGN = {"left": -1, "right": 1, "up_left": -1, "up_right": 1, "down_left": -1,
             "down_right": 1}  # fmt: skip
_PITCH_SIGN = {"up": 1, "down": -1, "up_left": 1, "up_right": 1, "down_left": -1,
               "down_right": -1}  # fmt: skip


def _deltas(args: dict) -> tuple[float | None, float | None]:
    """Yaw and pitch offsets of a look / turn call (None: the axis is not named)."""
    d = args["direction"]
    if "degrees" in args:
        yaw_mag = pitch_mag = float(args["degrees"])
    else:
        yaw_mag, pitch_mag = float(YAW_DEG[args["amount"]]), float(PITCH_DEG[args["amount"]])
    yaw = _YAW_SIGN[d] * yaw_mag if d in _YAW_SIGN else None
    pitch = _PITCH_SIGN[d] * pitch_mag if d in _PITCH_SIGN else None
    return yaw, pitch


def _move(yaw: float, pitch: float, limits: Limits) -> dict:
    y = min(max(yaw, limits.yaw_min), limits.yaw_max)
    p = min(max(pitch, limits.pitch_min), limits.pitch_max)
    return {"kind": "move", "yaw": y, "pitch": p, "clamped": (y, p) != (yaw, pitch)}


def plan_v1(
    calls: list[dict], start: tuple[float, float], limits: Limits = DEFAULT_LIMITS
) -> list[dict]:
    """Steps for one validated v1 output, starting from the pose ``start`` = (yaw, pitch).

    The firmware dispatcher (firmware/jtalm_action) must produce the same targets; it adds the
    motion timing and 200 ms between the two calls itself.
    """
    yaw, pitch = start
    steps: list[dict] = []

    def move(y: float, p: float) -> None:
        nonlocal yaw, pitch
        step = _move(y, p, limits)
        steps.append(step)
        yaw, pitch = step["yaw"], step["pitch"]

    def back_to(y: float, p: float) -> None:
        """The final return of nod / shake / bow, only when the pose differs (as in v0)."""
        if (yaw, pitch) != (y, p):
            move(y, p)

    for call in calls:
        name, args = call["name"], call["arguments"]
        if name in ("look", "turn"):
            if args["direction"] == "center":
                move(0, 0)
                continue
            dy, dp = _deltas(args)
            if name == "look":
                move(yaw if dy is None else dy, pitch if dp is None else dp)
            else:
                move(yaw + (dy or 0), pitch + (dp or 0))
        elif name == "nod":
            base = pitch
            for t in nod_targets(int(args["count"]), base, int(limits.pitch_min),
                                 int(limits.pitch_max)):  # fmt: skip
                move(yaw, float(t.pitch_deg))
            back_to(yaw, base)
        elif name == "shake":
            base = yaw
            for _ in range(int(args["count"])):
                move(base + SHAKE_YAW_DEG, pitch)
                move(base - SHAKE_YAW_DEG, pitch)
            back_to(base, pitch)
        elif name == "bow":
            base = pitch
            move(yaw, limits.pitch_min)
            steps.append({"kind": "pause", "ms": BOW_HOLD_MS})
            back_to(yaw, base)
        elif name == "set_expression":
            steps.append({"kind": "expr", "expression": args["expression"]})
        elif name == "set_led":
            steps.append({"kind": "led", "color": args["color"]})
        elif name in ("set_volume", "set_brightness"):
            steps.append({"kind": name.removeprefix("set_"), "level": int(args["level"])})
        elif name in ("adjust_volume", "adjust_brightness"):
            size = int(args["by"]) if "by" in args else ADJUST_STEP[args["amount"]]
            sign = 1 if args["direction"] == "up" else -1
            steps.append({"kind": name.removeprefix("adjust_"), "delta": sign * size})
        else:
            raise ValueError(f"unknown tool: {name}")
    return steps
```

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run pytest tests/test_mapping.py -q`
Expected: PASS（v0 の test もそのまま通る）

- [ ] **Step 5: Commit**

```bash
git add src/jtalm/action/mapping.py tests/test_mapping.py
git commit -m "mapping: plan_v1 (absolute look, relative turn, diagonals, shake, bow, LED/volume/brightness steps) as the firmware reference"
```

---

### Task 5: 評価の指標を v1 に

**Files:**
- Modify: `src/jtalm/eval/metrics.py`
- Modify: `tests/test_metrics.py`

**Interfaces:**
- Produces: `evaluate(...)` の戻り値に `"numeric": {"n": int, "exact": int, "mean_abs_error": float | None}` を足す。`critical` の `reverse_direction` は `look` / `turn` / `adjust_volume` / `adjust_brightness` の逆方向（斜めを含む）。

`rule_baseline.py` と `classifier.py` は変えない。v0 の出力は v1 でも正しいので、比較の基準としてそのまま使える（spec 5.1 の表のうち、この2つは「v1 の新しい動作を出さない基準」として残すことにした。Task 16 で spec と docs に書く）。

- [ ] **Step 1: 失敗する test を書く**

```python
def test_v1_reverse_direction_and_numeric_error() -> None:
    case = EvalCase(id="a", prompt="p", category="single",
                    expected=[{"name": "turn", "arguments": {"direction": "up_left", "degrees": 30}}])
    raw = '[{"name":"turn","arguments":{"direction":"down_right","degrees":30}}]'
    assert "reverse_direction" in score_case(case, raw).critical
    vol = EvalCase(id="b", prompt="p", category="single",
                   expected=[{"name": "set_volume", "arguments": {"level": 50}}])
    report = evaluate([vol], {"b": '[{"name":"set_volume","arguments":{"level":40}}]'})
    assert report["numeric"] == {"n": 1, "exact": 0, "mean_abs_error": 10.0}
```

（`EvalCase` と `score_case`、`evaluate` は `tests/test_metrics.py` で import 済み。なければ `from jtalm.eval.metrics import evaluate, score_case` と `from jtalm.eval.cases import EvalCase` を足す。）

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_metrics.py -q`
Expected: FAIL（`KeyError: 'numeric'`、`reverse_direction` がない）

- [ ] **Step 3: `metrics.py` を直す**

`OPPOSITE` を次にする。

```python
OPPOSITE = {"left": "right", "right": "left", "up": "down", "down": "up",
            "up_left": "down_right", "down_right": "up_left",
            "up_right": "down_left", "down_left": "up_right"}  # fmt: skip
DIRECTED = ("look", "turn", "adjust_volume", "adjust_brightness")
NUMERIC_ARGS = ("degrees", "count", "level", "by")
```

`score_case` の逆方向の判定を `if exp_call["name"] == pred_call["name"] and exp_call["name"] in DIRECTED:` に変える。`CaseResult` に `numeric_errors: tuple[float, ...]` を足し、`score_case` の中で、同じ名前の call の組ごとに、数値以外の引数がすべて等しく、同じ数値の引数を両方が持つときの `abs(pred - exp)` を集める。

```python
    numeric: list[float] = []
    if pred is not None:
        for exp_call, pred_call in zip(expected, pred, strict=False):
            if exp_call["name"] != pred_call["name"]:
                continue
            e, p = exp_call["arguments"], pred_call["arguments"]
            others = {k: v for k, v in e.items() if k not in NUMERIC_ARGS}
            if all(p.get(k) == v for k, v in others.items()):
                for k in NUMERIC_ARGS:
                    if k in e and isinstance(p.get(k), int | float):
                        numeric.append(abs(float(p[k]) - float(e[k])))
```

`evaluate` の戻り値に足す。

```python
    errors = [x for r in results for x in r.numeric_errors]
    ...
        "numeric": {
            "n": len(errors),
            "exact": sum(x == 0 for x in errors),
            "mean_abs_error": sum(errors) / len(errors) if errors else None,
        },
```

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run pytest tests/test_metrics.py tests/test_rule_baseline.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jtalm/eval/metrics.py tests/test_metrics.py
git commit -m "metrics: reverse direction for turn/adjust and diagonals; numeric slot error (count, exact, mean abs error)"
```

---

### Task 6: C の grammar を v1 に（と `--grammar-trace`）

**Files:**
- Modify: `runtime/host/grammar.c`（全体を書き換え）
- Modify: `runtime/host/jtalm.h:148-161`
- Modify: `runtime/host/model.c:619`
- Modify: `runtime/host/main.c`
- Modify: `tests/test_export.py`

**Interfaces:**
- Consumes: Python の `ActionGrammar`（Task 3）を正とする。
- Produces: `jtlm_grammar_init` / `jtlm_grammar_reset` / `jtlm_grammar_allowed` / `jtlm_grammar_advance`（名前と引数は v0 と同じ。`allowed` は最大 `JTLM_MAX_ALLOWED`（16）個を id の昇順で書く）。`jtalm --grammar-trace`: 入力の1行（空白区切りの id）ごとに `{"allowed":[[...],...]}`（長さ n の行に対し n + 1 個。i 番目は最初の i 個を進めた後の allowed）。

- [ ] **Step 1: 失敗する test を書く**

`tests/test_export.py` に足す（既存の `sp_model` fixture の tokenizer は v1 の部品を user-defined symbols に持つので、そのまま使える）。

```python
@pytest.mark.skipif(_compiler() is None, reason="no C compiler on PATH")
def test_c_grammar_matches_python(tmp_path: Path, sp_model: Path, model: ActionLM) -> None:
    import random

    from jtalm.model.format import all_call_pieces

    exe = tmp_path / "jtalm"
    src = ROOT / "runtime/host"
    subprocess.run([_compiler(), "-O1", "-std=c11", "-ffp-contract=off", "-o", str(exe),
                    *[str(src / f) for f in ("model.c", "tokenizer.c", "grammar.c", "main.c")],
                    "-lm"], check=True)  # fmt: skip
    out = tmp_path / "m.jtlm"
    export(model.state_dict(), model.cfg, sp_model, out)
    g = ActionGrammar(Codec(sp_model))
    calls = all_call_pieces()
    seqs = [[g.id["["], *(g.id[p] for p in c), g.id["]"]] for c in calls]
    rng = random.Random(0)
    for c in rng.sample(calls, 400):  # the second call follows the first as far as allowed
        ids = [g.id["["], *(g.id[p] for p in c), g.id[","]]
        for p in c:
            if g.id[p] not in g.allowed(ids):
                break
            ids.append(g.id[p])
        seqs.append(ids)
    for _ in range(400):
        ids = []
        while (nxt := rng.choice(g.allowed(ids))) != g.eos:
            ids.append(nxt)
        seqs.append(ids)
    inp = tmp_path / "seqs.txt"
    inp.write_text("\n".join(" ".join(map(str, s)) for s in seqs) + "\n")
    proc = subprocess.run([str(exe), "-m", str(out), "-i", str(inp), "--grammar-trace"],
                          check=True, capture_output=True)  # fmt: skip
    rows = [json.loads(x) for x in proc.stdout.decode().splitlines() if x.strip()]
    assert len(rows) == len(seqs)
    for s, r in zip(seqs, rows, strict=True):
        expected = [g.allowed(s[:i]) for i in range(len(s) + 1)]
        assert r["allowed"] == expected, s
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run --group train pytest tests/test_export.py -q -k "grammar or c_runtime"`
Expected: FAIL（`--grammar-trace` を知らない、または v1 の部品の init に失敗する）。gcc がない Windows では skip になるので、Docker の gcc で確かめる。

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/w" -w /w --entrypoint sh espressif/idf:v5.5.5 -c "pip install -q uv && uv run --group train pytest -q tests/test_export.py -k 'grammar or c_runtime'"
```

（Docker の image に uv を入れるのに時間がかかる場合は、CI の Linux runner で確かめてもよい。どちらで確かめたかを commit message に書く。）

- [ ] **Step 3: `jtalm.h` の grammar の部分を書き換える**

```c
/* Action schema v1 grammar (port of jtalm.model.grammar; tool table of jtalm.action.schema). */
#define JTLM_N_TOOLS 11
#define JTLM_MAX_ALLOWED 16 /* the most: 11 call heads, or 10 digits + a closer */
#define JTLM_CALL_MAX 7     /* head, value, key, three digits, closer */

typedef struct {
    int head;
    int n_values, values[10]; /* first argument as enum ids; n_values == 0: a number lo..hi */
    int lo, hi;               /* lo > hi with n_values == 0: no arguments (bow) */
    int second;               /* 0: none, 1: amount | degrees, 2: amount | by */
} jtlm_tool;

typedef struct {
    int eos, empty, open, close, comma, close_str, close_num;
    int key_amount, key_degrees, key_by;
    int amounts[3], digits[10];
    int center, normal, look; /* look toward center takes only amount normal */
    jtlm_tool tools[JTLM_N_TOOLS];
} jtlm_grammar;

typedef struct {
    int step, phase, tool;
    int lo, hi, value, n_digits; /* the number being written */
    int n_calls, calls[2][JTLM_CALL_MAX], call_len[2];
    int n_cur, cur[JTLM_CALL_MAX];
} jtlm_grammar_state;

int jtlm_grammar_init(jtlm_grammar *g, const jtlm_tokenizer *t, void *work, size_t work_bytes);
void jtlm_grammar_reset(jtlm_grammar_state *st);
/* Writes the allowed ids (at most JTLM_MAX_ALLOWED, ascending) after the tokens consumed so far;
 * returns their count. */
int jtlm_grammar_allowed(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids);
void jtlm_grammar_advance(const jtlm_grammar *g, jtlm_grammar_state *st, int token);
```

- [ ] **Step 4: `grammar.c` を書き換える**

```c
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
/* Action schema v1 grammar: a port of jtalm.model.grammar.ActionGrammar.
 *
 *     [] </s>  |  [ CALL ] </s>  |  [ CALL , CALL ] </s>   (the second call differs from the first)
 *     CALL = HEAD first [ KEY second ] CLOSE  |  BOW
 *
 * Enum values are one token; numbers are one token per digit, without a leading zero and inside
 * the argument's range. The Python version walks a trie of every call; this one applies the same
 * rules directly. tests/test_export.py::test_c_grammar_matches_python compares the two on every
 * single call, on duplicate-prone pairs, and on random walks. */
#include <string.h>

#include "jtalm.h"

enum { START, CALL, AFTER_CALL, EMPTY, END, DONE };
enum { P_HEAD, P_FIRST, P_KEY, P_SECOND, P_CLOSE_STR, P_NUM };

static const char *const DIRS[9] = {"left", "right", "up", "down", "up_left", "up_right",
                                    "down_left", "down_right", "center"};
static const char *const AMOUNTS[3] = {"slight", "normal", "large"};
static const char *const EXPRS[7] = {"happy", "sad", "surprised", "neutral", "angry", "sleepy",
                                     "doubt"};
static const char *const COLORS[10] = {"red", "orange", "yellow", "green", "light_blue", "blue",
                                       "purple", "pink", "white", "off"};
static const char *const UPDOWN[2] = {"up", "down"};

/* Same order and values as jtalm.action.schema.TOOLS. */
static const struct {
    const char *head;
    const char *const *values;
    int n_values, lo, hi, second;
} TOOLS[JTLM_N_TOOLS] = {
    {"{\"name\":\"look\",\"arguments\":{\"direction\":\"", DIRS, 9, 0, 0, 1},
    {"{\"name\":\"turn\",\"arguments\":{\"direction\":\"", DIRS, 8, 0, 0, 1},
    {"{\"name\":\"nod\",\"arguments\":{\"count\":", NULL, 0, 1, 5, 0},
    {"{\"name\":\"shake\",\"arguments\":{\"count\":", NULL, 0, 1, 5, 0},
    {"{\"name\":\"bow\",\"arguments\":{}}", NULL, 0, 1, 0, 0},
    {"{\"name\":\"set_expression\",\"arguments\":{\"expression\":\"", EXPRS, 7, 0, 0, 0},
    {"{\"name\":\"set_led\",\"arguments\":{\"color\":\"", COLORS, 10, 0, 0, 0},
    {"{\"name\":\"set_volume\",\"arguments\":{\"level\":", NULL, 0, 0, 100, 0},
    {"{\"name\":\"adjust_volume\",\"arguments\":{\"direction\":\"", UPDOWN, 2, 0, 0, 2},
    {"{\"name\":\"set_brightness\",\"arguments\":{\"level\":", NULL, 0, 0, 100, 0},
    {"{\"name\":\"adjust_brightness\",\"arguments\":{\"direction\":\"", UPDOWN, 2, 0, 0, 2},
};

/* The id of a piece that must encode to exactly one token (ActionGrammar.tid). */
static int tid(const jtlm_tokenizer *t, const char *piece, void *work, size_t work_bytes) {
    int ids[2];
    int n = jtlm_encode(t, piece, strlen(piece), ids, 2, work, work_bytes);
    return n == 1 ? ids[0] : -1;
}

int jtlm_grammar_init(jtlm_grammar *g, const jtlm_tokenizer *t, void *work, size_t work_bytes) {
    static const char *const digits[10] = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"};
    int ok = 1;
#define TID(dst, piece) ok &= ((dst) = tid(t, (piece), work, work_bytes)) >= 0
    g->eos = t->eos;
    TID(g->empty, "[]");
    TID(g->open, "[");
    TID(g->close, "]");
    TID(g->comma, ",");
    TID(g->close_str, "\"}}");
    TID(g->close_num, "}}");
    TID(g->key_amount, "\",\"amount\":\"");
    TID(g->key_degrees, "\",\"degrees\":");
    TID(g->key_by, "\",\"by\":");
    for (int i = 0; i < 3; i++) TID(g->amounts[i], AMOUNTS[i]);
    for (int i = 0; i < 10; i++) TID(g->digits[i], digits[i]);
    TID(g->center, "center");
    TID(g->normal, "normal");
    for (int i = 0; i < JTLM_N_TOOLS; i++) {
        jtlm_tool *tool = &g->tools[i];
        TID(tool->head, TOOLS[i].head);
        tool->n_values = TOOLS[i].n_values;
        for (int k = 0; k < tool->n_values; k++) TID(tool->values[k], TOOLS[i].values[k]);
        tool->lo = TOOLS[i].lo;
        tool->hi = TOOLS[i].hi;
        tool->second = TOOLS[i].second;
    }
    g->look = g->tools[0].head;
#undef TID
    return ok ? JTLM_OK : JTLM_ERR_FORMAT;
}

void jtlm_grammar_reset(jtlm_grammar_state *st) { memset(st, 0, sizeof(*st)); }

static int digit_of(const jtlm_grammar *g, int token) {
    for (int d = 0; d < 10; d++)
        if (g->digits[d] == token) return d;
    return -1;
}

static void complete_call(jtlm_grammar_state *st) {
    if (st->n_calls < 2) {
        memcpy(st->calls[st->n_calls], st->cur, (size_t)st->n_cur * sizeof(int));
        st->call_len[st->n_calls] = st->n_cur;
        st->n_calls++;
    }
    st->n_cur = 0;
    st->phase = P_HEAD;
    st->step = AFTER_CALL;
}

static void start_number(jtlm_grammar_state *st, int lo, int hi) {
    st->phase = P_NUM;
    st->lo = lo;
    st->hi = hi;
    st->value = 0;
    st->n_digits = 0;
}

void jtlm_grammar_advance(const jtlm_grammar *g, jtlm_grammar_state *st, int token) {
    switch (st->step) {
    case START:
        st->step = token == g->empty ? EMPTY : CALL;
        st->phase = P_HEAD;
        break;
    case CALL: {
        if (st->n_cur < JTLM_CALL_MAX) st->cur[st->n_cur++] = token;
        const jtlm_tool *tool = &g->tools[st->tool];
        switch (st->phase) {
        case P_HEAD:
            for (int i = 0; i < JTLM_N_TOOLS; i++)
                if (g->tools[i].head == token) st->tool = i;
            tool = &g->tools[st->tool];
            if (tool->n_values) st->phase = P_FIRST;
            else if (tool->lo > tool->hi) complete_call(st); /* bow */
            else start_number(st, tool->lo, tool->hi);
            break;
        case P_FIRST:
            st->phase = tool->second ? P_KEY : P_CLOSE_STR;
            break;
        case P_KEY:
            if (token == g->key_amount) st->phase = P_SECOND;
            else start_number(st, 1, token == g->key_degrees ? 180 : 100);
            break;
        case P_SECOND:
            st->phase = P_CLOSE_STR;
            break;
        case P_CLOSE_STR:
            complete_call(st);
            break;
        default: /* P_NUM */
            if (token == g->close_num) complete_call(st);
            else {
                st->value = st->value * 10 + digit_of(g, token);
                st->n_digits++;
            }
            break;
        }
        break;
    }
    case AFTER_CALL:
        st->step = token == g->comma ? CALL : END;
        st->phase = P_HEAD;
        break;
    default: /* EMPTY, END, DONE */
        st->step = DONE;
        break;
    }
}

static int pow10i(int n) {
    int p = 1;
    while (n-- > 0) p *= 10;
    return p;
}

static int n_digits_of(int v) {
    int n = 1;
    while (v >= 10) {
        v /= 10;
        n++;
    }
    return n;
}

/* 1 when v, written without leading zeros, starts with the len digits of p. */
static int has_prefix(int v, int p, int len) {
    int n = n_digits_of(v);
    return n >= len && v / pow10i(n - len) == p;
}

/* The digits (and the closer) that keep the number inside [lo, hi] with a completion other than
 * dup (dup < 0: no duplicate to avoid). */
static int number_options(const jtlm_grammar *g, const jtlm_grammar_state *st, int dup, int *ids) {
    int k = 0;
    for (int d = 0; d <= 9; d++) {
        int p = st->value * 10 + d;
        for (int v = st->lo; v <= st->hi; v++)
            if (v != dup && has_prefix(v, p, st->n_digits + 1)) {
                ids[k++] = g->digits[d];
                break;
            }
    }
    if (st->n_digits > 0 && st->value >= st->lo && st->value <= st->hi && st->value != dup)
        ids[k++] = g->close_num;
    return k;
}

/* The first call's number when the call being built equals it up to here, else -1. */
static int duplicate_number(const jtlm_grammar *g, const jtlm_grammar_state *st, int same) {
    if (!same) return -1;
    const int *first = st->calls[0];
    int start = st->n_cur - st->n_digits, v = 0;
    for (int i = start; i < st->call_len[0] && first[i] != g->close_num; i++)
        v = v * 10 + digit_of(g, first[i]);
    return v;
}

static void sort_ids(int *ids, int k) {
    for (int i = 1; i < k; i++)
        for (int j = i; j > 0 && ids[j - 1] > ids[j]; j--) {
            int tmp = ids[j];
            ids[j] = ids[j - 1];
            ids[j - 1] = tmp;
        }
}

static int call_options(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids) {
    const int *first = st->calls[0];
    /* same: the call being built equals the first call so far (the first call is longer) */
    int same = st->n_calls >= 1 && st->call_len[0] > st->n_cur &&
               memcmp(first, st->cur, (size_t)st->n_cur * sizeof(int)) == 0;
    const jtlm_tool *tool = &g->tools[st->tool];
    int k = 0;
    switch (st->phase) {
    case P_HEAD:
        for (int i = 0; i < JTLM_N_TOOLS; i++) {
            const jtlm_tool *t = &g->tools[i];
            int whole = t->n_values == 0 && t->lo > t->hi; /* bow is one piece */
            if (whole && same && st->call_len[0] == 1 && first[0] == t->head) continue;
            ids[k++] = t->head;
        }
        return k;
    case P_FIRST:
        for (int i = 0; i < tool->n_values; i++) {
            int v = tool->values[i];
            int only_one = !tool->second || (tool->head == g->look && v == g->center);
            if (only_one && same && first[1] == v) continue;
            ids[k++] = v;
        }
        return k;
    case P_KEY:
        ids[k++] = g->key_amount;
        if (!(tool->head == g->look && st->cur[1] == g->center))
            ids[k++] = tool->second == 1 ? g->key_degrees : g->key_by;
        return k;
    case P_SECOND:
        if (tool->head == g->look && st->cur[1] == g->center) {
            ids[k++] = g->normal; /* the first call cannot be look center: P_FIRST dropped it */
            return k;
        }
        for (int i = 0; i < 3; i++)
            if (!(same && first[st->n_cur] == g->amounts[i])) ids[k++] = g->amounts[i];
        return k;
    case P_CLOSE_STR:
        ids[k++] = g->close_str;
        return k;
    default: /* P_NUM */
        return number_options(g, st, duplicate_number(g, st, same), ids);
    }
}

int jtlm_grammar_allowed(const jtlm_grammar *g, const jtlm_grammar_state *st, int *ids) {
    int k;
    switch (st->step) {
    case START:
        ids[0] = g->empty;
        ids[1] = g->open;
        k = 2;
        break;
    case CALL:
        k = call_options(g, st, ids);
        break;
    case AFTER_CALL:
        if (st->n_calls == 1) {
            ids[0] = g->comma;
            ids[1] = g->close;
            k = 2;
        } else {
            ids[0] = g->close;
            k = 1;
        }
        break;
    default:
        ids[0] = g->eos;
        k = 1;
        break;
    }
    sort_ids(ids, k);
    return k;
}
```

- [ ] **Step 5: `model.c` と `main.c` を直す**

`runtime/host/model.c:619` の `int allowed[8]` を `int allowed[JTLM_MAX_ALLOWED]` にする。

`runtime/host/main.c` を次のように直す。

1. 先頭のコメントと `usage()` に `jtalm -m MODEL.jtlm --grammar-trace [-i FILE]   (id lines -> allowed ids per prefix)` を足す。
2. `int use_grammar = 0, tokenize = 0, decode = 0, first_logits = 0;` に `trace = 0` を足し、引数の解析に `else if (!strcmp(argv[i], "--grammar-trace")) trace = 1;` を足す。
3. grammar の初期化の条件を `if ((use_grammar || trace) && jtlm_grammar_init(...) != JTLM_OK)` にする。
4. 行の loop の中、BOM を除いた直後（`if (decode) {` の前）に次を足す。

```c
        if (trace) { /* allowed ids before each token of the line and after the last one */
            int n = 0;
            for (char *p = text, *end; n < 4096; p = end) {
                long v = strtol(p, &end, 10);
                if (end == p) break;
                ids[n++] = (int)v;
            }
            jtlm_grammar_state st;
            jtlm_grammar_reset(&st);
            fputs("{\"allowed\":[", stdout);
            for (int i = 0; i <= n; i++) {
                int allowed[JTLM_MAX_ALLOWED], k = jtlm_grammar_allowed(&grammar, &st, allowed);
                if (i) putchar(',');
                print_ids(allowed, k);
                if (i < n) jtlm_grammar_advance(&grammar, &st, ids[i]);
            }
            fputs("]}\n", stdout);
            continue;
        }
```

5. 最後の時間の要約の条件を `if (!tokenize && !decode && !trace && n_lines)` にする。

- [ ] **Step 6: test が通ることを確かめる**

Docker の gcc で Step 2 のコマンドを再実行する。

Expected: `test_c_grammar_matches_python` と `test_c_runtime_matches_python`（`kv_int8` の両方）が PASS。

- [ ] **Step 7: host の binary を作り直し、CI と同じ build が通ることを確かめる**

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/w" -w /w --entrypoint make espressif/idf:v5.5.5 -C runtime/host
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/w" -w /w --entrypoint sh espressif/idf:v5.5.5 -c "cmake -S runtime/host -B runtime/host/build/cmake && cmake --build runtime/host/build/cmake"
```

Expected: どちらも warning なしで成功する。

- [ ] **Step 8: Commit**

```bash
git add runtime/host/grammar.c runtime/host/jtalm.h runtime/host/model.c runtime/host/main.c tests/test_export.py
git commit -m "runtime/host: schema v1 grammar (numbers digit by digit, duplicates cut), --grammar-trace; equal to the Python grammar on every single call, duplicate-prone pairs and random walks"
```

---

### Task 7: HF 用の推論スクリプト、配布、Web デモを v1 に

**Files:**
- Modify: `src/jtalm/model/hf_inference.py`（grammar の部分と定数）
- Modify: `src/jtalm/model/release.py:38,87,102,196,198`
- Modify: `runtime/web/index.html`（説明、例、`describe`）
- Create: `tests/test_hf_inference.py`

**Interfaces:**
- Consumes: `ActionGrammar`（Task 3）を正とする。
- Produces: `hf_inference.Grammar(sp)` と `.allowed(generated) -> list[int]`（昇順）。`release.py` は `action_schema_v1.json` を配る。

- [ ] **Step 1: 失敗する test を書く**

`tests/test_hf_inference.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import random

import pytest

pytest.importorskip("torch")
pytest.importorskip("sentencepiece")

from jtalm.model import hf_inference, tokenizer  # noqa: E402
from jtalm.model.data import Codec  # noqa: E402
from jtalm.model.format import target_json  # noqa: E402
from jtalm.model.grammar import ActionGrammar  # noqa: E402


def test_standalone_grammar_equals_the_project_grammar(tmp_path) -> None:
    lines = [target_json([{"name": "bow", "arguments": {}}])] * 20 + ["右を向いて"] * 20
    codec = Codec(tokenizer.train(lines, 400, tmp_path / "t"))
    ours, theirs = ActionGrammar(codec), hf_inference.Grammar(codec.sp)
    rng = random.Random(1)
    for _ in range(500):
        ids: list[int] = []
        while True:
            options = ours.allowed(ids)
            assert theirs.allowed(ids) == options, ids
            nxt = rng.choice(options)
            if nxt == ours.eos:
                break
            ids.append(nxt)
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run --group train pytest tests/test_hf_inference.py -q`
Expected: FAIL（v0 の Grammar は v1 の部品を知らない）

- [ ] **Step 3: `hf_inference.py` の定数と `Grammar` を書き換える**

docstring の `Decoding is greedy with the Action schema grammar` の段落はそのまま残す。定数（`DIRECTIONS` から `NOD` まで）を次に置き換える。

```python
MAX_TARGET_TOKENS = 24
DIRECTIONS = ("left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right",
              "center")  # fmt: skip
AMOUNTS = ("slight", "normal", "large")
# Action schema v1 (action_schema_v1.json): tool -> (first argument, its values or range,
# {second argument: its values or range}). A range is a Python range of integers.
TOOLS = {
    "look": ("direction", DIRECTIONS, {"amount": AMOUNTS, "degrees": range(1, 181)}),
    "turn": ("direction", DIRECTIONS[:-1], {"amount": AMOUNTS, "degrees": range(1, 181)}),
    "nod": ("count", range(1, 6), {}),
    "shake": ("count", range(1, 6), {}),
    "bow": (None, (), {}),
    "set_expression": ("expression", ("happy", "sad", "surprised", "neutral", "angry",
                                      "sleepy", "doubt"), {}),
    "set_led": ("color", ("red", "orange", "yellow", "green", "light_blue", "blue", "purple",
                          "pink", "white", "off"), {}),
    "set_volume": ("level", range(0, 101), {}),
    "adjust_volume": ("direction", ("up", "down"), {"amount": AMOUNTS, "by": range(1, 101)}),
    "set_brightness": ("level", range(0, 101), {}),
    "adjust_brightness": ("direction", ("up", "down"), {"amount": AMOUNTS, "by": range(1, 101)}),
}  # fmt: skip


def _options(values) -> list[tuple[str, ...]]:
    if isinstance(values, range):
        return [tuple(str(n)) for n in values]
    return [(v,) for v in values]


def _q(values) -> str:
    return "" if isinstance(values, range) else '"'


def call_pieces() -> list[tuple[str, ...]]:
    """Every valid call as its token pieces (look toward center takes only amount normal)."""
    calls = []
    for name, (key, first, seconds) in TOOLS.items():
        if key is None:
            calls.append((f'{{"name":"{name}","arguments":{{}}}}',))
            continue
        head = f'{{"name":"{name}","arguments":{{"{key}":{_q(first)}'
        for value in _options(first):
            if not seconds:
                calls.append((head, *value, '"}}' if _q(first) else "}}"))
                continue
            for skey, svalues in seconds.items():
                options = _options(svalues)
                if name == "look" and value == ("center",):
                    if skey != "amount":
                        continue
                    options = [("normal",)]
                for w in options:
                    calls.append((head, *value, f'","{skey}":{_q(svalues)}', *w,
                                  '"}}' if _q(svalues) else "}}"))  # fmt: skip
    return calls
```

`class Grammar` を、Task 3 の `ActionGrammar` と同じ trie の実装（`__init__` は `sp` を受け取り、`all_call_pieces()` の代わりに `call_pieces()` を使い、`tid` は `assert len(ids) == 1, piece`）に置き換える。`_parse` と `allowed` は Task 3 のコードをそのまま写す（docstring は「`[] | [ CALL ] | [ CALL , CALL ]`、the second call differs from the first」とする）。`ActionModel` 側の呼び出し（`self.grammar.allowed(generated)`）は変えない。

- [ ] **Step 4: `release.py` を直す**

- `SCHEMA = PROJECT_ROOT / "src/jtalm/action/action_schema_v1.json"`
- `shutil.copy(SCHEMA, out / "action_schema_v1.json")`、`"schema": "action_schema_v1.json"`
- `--tokenizer` の既定値を `PROJECT_ROOT / "tokenizer/out/action_v1_sp2048.model"`（Task 12 で作る）、`--data-version` の既定値を `"action v1.0"` にする。

- [ ] **Step 5: Web デモの表示を直す**

`runtime/web/index.html` の説明の `<li>` を、11 の動作が分かる文にする（「首を向ける（絶対・相対、角度も可）、うなずく、首を横に振る、お辞儀、表情（7種類）、LED の色、音量、画面の明るさ」）。`EXAMPLES` に、spec 4.4 の入力のうち公開例と利用者の文（「LEDライトの色を青にして」「音声の音量を50にして」「頭を90度上に向けて」「顔を右に45度向いて」「もう少し右」「寝室のライトをつけて」）を足す。`describe` を次にする。

```js
const DIRECTION = { left: "左", right: "右", up: "上", down: "下", up_left: "左上", up_right: "右上",
  down_left: "左下", down_right: "右下", center: "正面" };
const AMOUNT = { slight: "少し", normal: "", large: "大きく" };
const EXPRESSION = { happy: "笑顔", sad: "悲しい顔", surprised: "驚いた顔", neutral: "普通の顔",
  angry: "怒った顔", sleepy: "眠そうな顔", doubt: "不思議そうな顔" };
const COLOR = { red: "赤", orange: "オレンジ", yellow: "黄色", green: "緑", light_blue: "水色",
  blue: "青", purple: "紫", pink: "ピンク", white: "白" };
const UPDOWN = { up: "上げる", down: "下げる" };

function size(a) { return "degrees" in a ? `${a.degrees}度` : AMOUNT[a.amount]; }
function describe(call) {
  const a = call.arguments;
  switch (call.name) {
    case "look": return a.direction === "center" ? "正面を向く" : `${DIRECTION[a.direction]}を${size(a)}向く`;
    case "turn": return `今の向きから${DIRECTION[a.direction]}へ${size(a) || "普通に"}動く`;
    case "nod": return `${a.count}回うなずく`;
    case "shake": return `首を横に${a.count}回振る`;
    case "bow": return "お辞儀する";
    case "set_expression": return `${EXPRESSION[a.expression]}にする`;
    case "set_led": return a.color === "off" ? "LED を消す" : `LED を${COLOR[a.color]}にする`;
    case "set_volume": return `音量を${a.level}にする`;
    case "set_brightness": return `画面の明るさを${a.level}にする`;
    case "adjust_volume": return `音量を${"by" in a ? a.by : AMOUNT[a.amount]}${UPDOWN[a.direction]}`;
    case "adjust_brightness": return `明るさを${"by" in a ? a.by : AMOUNT[a.amount]}${UPDOWN[a.direction]}`;
  }
  return JSON.stringify(call);
}
```

（`jtalm.js` の再 build と Space の更新は Task 15。）

- [ ] **Step 6: test が通ることを確かめる**

Run: `uv run --group train pytest tests/test_hf_inference.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/jtalm/model/hf_inference.py src/jtalm/model/release.py runtime/web/index.html tests/test_hf_inference.py
git commit -m "Standalone inference.py, release files and the web demo for schema v1"
```

---

### Task 8: v1 のデータの spec と prompt

**Files:**
- Create: `src/jtalm/data/specs_v1.py`
- Modify: `src/jtalm/data/prompts.py`
- Modify: `src/jtalm/data/massive.py`
- Create: `tests/test_data_specs_v1.py`

**Interfaces:**
- Consumes: `Spec`（`jtalm.data.specs`）、`validate`（Task 1）
- Produces:
  - `specs_v1.all_specs_v1(seed: int = 20261002) -> list[Spec]`（単体、組み合わせ、否定、訂正、`[]`、範囲外の6種類。spec id は `v1.<category>.<detail>`）
  - `specs_v1.paraphrase_specs(seed: int = 20261003) -> list[Spec]`（実例セットの言い換え用。look / turn の角度と量だけ）
  - `specs_v1.describe(call) -> str`
  - `prompts.PROMPT_VERSION = "action-v1.0"`、`prompts.VERIFY_SYSTEM`（v1）
  - `massive.VOLUME_INTENTS`

- [ ] **Step 1: 失敗する test を書く**

`tests/test_data_specs_v1.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
from collections import Counter

from jtalm.action.schema import TOOLS, validate
from jtalm.data import prompts
from jtalm.data.specs_v1 import all_specs_v1, describe, paraphrase_specs


def test_every_spec_label_is_valid_and_ids_are_unique() -> None:
    specs = all_specs_v1()
    assert len({s.id for s in specs}) == len(specs)
    for s in specs:
        assert validate(list(s.label)) == [], s.id
        assert s.meaning


def test_every_tool_appears_in_single_specs() -> None:
    names = {c["name"] for s in all_specs_v1() if s.category == "single" for c in s.label}
    assert names == set(TOOLS)


def test_number_specs_ask_for_each_notation() -> None:
    hints = Counter(s.hint for s in all_specs_v1() if "degrees" in str(s.label))
    assert {h for h in hints if h} >= {"算用数字（例: 45）で書く", "漢数字（例: 四十五）で書く",
                                       "全角の数字（例: ４５）で書く"}  # fmt: skip


def test_out_of_range_specs_are_labeled_with_the_maximum() -> None:
    oor = [s for s in all_specs_v1() if s.id.startswith("v1.single.out_of_range")]
    assert oor and all(s.label[0]["arguments"]["level"] == 100 for s in oor)


def test_describe_and_prompts_cover_v1() -> None:
    assert describe({"name": "turn", "arguments": {"direction": "right", "degrees": 10}}) == (
        "今の向きから、さらに右へ10度首を動かす")
    assert "set_led" in prompts.VERIFY_SYSTEM and "turn" in prompts.VERIFY_SYSTEM
    assert prompts.PROMPT_VERSION == "action-v1.0"
    reqs = prompts.requirements(next(s for s in all_specs_v1() if s.id.startswith("v1.single.turn")))
    assert any("今の向き" in r for r in reqs)
    assert all(s.label[0]["name"] in ("look", "turn") for s in paraphrase_specs())
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_data_specs_v1.py -q`
Expected: FAIL（`ModuleNotFoundError: jtalm.data.specs_v1`）

- [ ] **Step 3: `specs_v1.py` を書く**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Label-first specs for Action schema v1 data (data v1.0, eval v3, the Stack-chan paraphrases).

Data v1.0 keeps the v0.5.1 sentences (re-verified under schema v1, jtalm.data.build_v1) and adds
sentences for the new tools and arguments. As in v0 (jtalm.data.specs) a spec fixes the label;
writers only write sentences, and Qwen3 keeps a sentence only if its parse equals the label.
Numbers are asked for in several notations so that 45, ４５ and 四十五 all map to 45.
"""

import itertools
import random

from jtalm.action.schema import TURN_DIRECTIONS, Call
from jtalm.data.specs import EXPR_DESC, Spec

DIR_JA = {"left": "左", "right": "右", "up": "上", "down": "下", "up_left": "左上",
          "up_right": "右上", "down_left": "左下", "down_right": "右下"}  # fmt: skip
AMOUNT_JA = {"slight": "少しだけ", "normal": "", "large": "大きく"}
EXPR_JA = {**EXPR_DESC, "angry": "怒った表情にする", "sleepy": "眠そうな表情にする",
           "doubt": "不思議そうな（困ったような）表情にする"}  # fmt: skip
COLOR_JA = {"red": "赤", "orange": "オレンジ", "yellow": "黄色", "green": "緑",
            "light_blue": "水色", "blue": "青", "purple": "紫", "pink": "ピンク", "white": "白"}  # fmt: skip
NUMBER_STYLES = ("算用数字（例: 45）で書く", "漢数字（例: 四十五）で書く",
                 "全角の数字（例: ４５）で書く")  # fmt: skip
LEVEL_STYLES = (*NUMBER_STYLES, "「%」か「パーセント」を付けて書く")
DEGREE_VALUES = (5, 10, 15, 20, 25, 30, 40, 45, 50, 60, 70, 80, 90, 100, 120, 135, 150, 180)
TURN_DEGREE_VALUES = (5, 10, 15, 20, 30, 45, 90)
LEVEL_VALUES = (0, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100)
BY_VALUES = (5, 10, 15, 20, 25, 30, 50)
CONFUSER_TOPICS = {
    "other_devices": (
        "ロボット以外の機器（部屋の照明、寝室のライト、エアコン、テレビ、スマホ、扇風機など）の"
        "操作の依頼（例: ライトをつける、エアコンの温度を変える、テレビの音量を上げる）"
    ),
    "numbers_not_actions": (
        "数字や「度」「%」が入っているが、ロボットの動作の依頼ではない文（気温や室温の話、"
        "タイマーや時間、計算、値段、確率など）"
    ),
    "direction_not_command": (
        "左右や上下などの方向の言葉が入っているが、ロボットへの依頼ではない文（物を置いた場所の話、"
        "道案内の話など）"
    ),
    "assistant_tasks": (
        "時刻、天気、ニュース、タイマー、アラーム、メモ、音楽の再生、歌、踊り、写真など、"
        "このロボットにはできない依頼"
    ),
    "face_or_color_talk": (
        "顔や表情、色、明るさについての話だが、ロボットへの依頼ではない文（絵や写真の顔の話、"
        "好きな色の話、部屋が暗いという感想など）"
    ),
}


def look(direction: str, amount: str | None = None, degrees: int | None = None) -> Call:
    args: dict = {"direction": direction}
    args.update({"degrees": degrees} if degrees is not None else {"amount": amount or "normal"})
    return {"name": "look", "arguments": args}


def turn(direction: str, amount: str | None = None, degrees: int | None = None) -> Call:
    return {**look(direction, amount, degrees), "name": "turn"}


def _count(name: str, n: int) -> Call:
    return {"name": name, "arguments": {"count": n}}


def bow() -> Call:
    return {"name": "bow", "arguments": {}}


def expression(value: str) -> Call:
    return {"name": "set_expression", "arguments": {"expression": value}}


def led(color: str) -> Call:
    return {"name": "set_led", "arguments": {"color": color}}


def level(target: str, value: int) -> Call:
    return {"name": f"set_{target}", "arguments": {"level": value}}


def adjust(target: str, direction: str, amount: str | None = None, by: int | None = None) -> Call:
    args: dict = {"direction": direction}
    args.update({"by": by} if by is not None else {"amount": amount or "normal"})
    return {"name": f"adjust_{target}", "arguments": args}


TARGET_JA = {"volume": "スピーカーの音量", "brightness": "画面の明るさ"}


def describe(call: Call) -> str:
    """Japanese meaning of one v1 call, used inside generation prompts."""
    name, a = call["name"], call["arguments"]
    if name == "look":
        if a["direction"] == "center":
            return "正面（真ん中）に向き直る"
        if "degrees" in a:
            return f"正面を基準に、{DIR_JA[a['direction']]}へ{a['degrees']}度の向きに首を向ける"
        return f"{AMOUNT_JA[a['amount']]}{DIR_JA[a['direction']]}を向く"
    if name == "turn":
        if "degrees" in a:
            return f"今の向きから、さらに{DIR_JA[a['direction']]}へ{a['degrees']}度首を動かす"
        return f"今の向きから、さらに{AMOUNT_JA[a['amount']]}{DIR_JA[a['direction']]}へ首を動かす"
    if name == "nod":
        return f"{a['count']}回うなずく"
    if name == "shake":
        return f"首を横に{a['count']}回振る（いやいやをする）"
    if name == "bow":
        return "お辞儀をする"
    if name == "set_expression":
        return EXPR_JA[a["expression"]]
    if name == "set_led":
        return "台座のLEDライトを消す" if a["color"] == "off" else (
            f"台座のLEDライトの色を{COLOR_JA[a['color']]}にする")
    if name.startswith("set_"):
        target = name.removeprefix("set_")
        if target == "volume" and a["level"] == 0:
            return "スピーカーの音を消す（消音にする）"
        return f"{TARGET_JA[target]}を{a['level']}にする"
    target = name.removeprefix("adjust_")
    up = a["direction"] == "up"
    if "by" in a:  # 「スピーカーの音量を10だけ上げる」「画面の明るさを10だけ下げる」
        return f"{TARGET_JA[target]}を{a['by']}だけ{'上げる' if up else '下げる'}"
    amount = AMOUNT_JA[a["amount"]]
    if target == "volume":  # 「スピーカーの音量を少しだけ上げる」
        return f"{TARGET_JA[target]}を{amount}{'上げる' if up else '下げる'}"
    return f"画面を{amount}{'明るくする' if up else '暗くする'}"  # 「画面を少しだけ暗くする」


def _id(call: Call) -> str:
    return ".".join([call["name"], *(str(v) for v in call["arguments"].values())])


def _single(call: Call, hint: str = "", tag: str = "") -> Spec:
    detail = _id(call) + (f".{tag}" if tag else "")
    return Spec(f"v1.single.{detail}", "single", (call,), f"ロボットに「{describe(call)}」ように頼む",
                hint)  # fmt: skip


def single_specs(rng: random.Random) -> list[Spec]:
    specs: list[Spec] = []
    for d in ("up_left", "up_right", "down_left", "down_right"):
        specs += [_single(look(d, a)) for a in AMOUNT_JA]
    extra = rng.sample([n for n in range(1, 181) if n not in DEGREE_VALUES], 3)
    for d in TURN_DIRECTIONS:
        for i, n in enumerate((*DEGREE_VALUES, *extra)):
            specs.append(_single(look(d, degrees=n), NUMBER_STYLES[i % 3], f"s{i % 3}"))
        specs += [_single(turn(d, a)) for a in AMOUNT_JA]
        for i, n in enumerate(TURN_DEGREE_VALUES):
            specs.append(_single(turn(d, degrees=n), NUMBER_STYLES[i % 3], f"s{i % 3}"))
    specs += [_single(_count("nod", n)) for n in (4, 5)]
    specs += [_single(_count("shake", n)) for n in (1, 2, 3, 4, 5)]
    specs += [_single(bow())]
    specs += [_single(expression(e)) for e in ("angry", "sleepy", "doubt")]
    specs += [_single(led(c)) for c in (*COLOR_JA, "off")]
    extra_levels = rng.sample([n for n in range(1, 100) if n not in LEVEL_VALUES], 5)
    for target in ("volume", "brightness"):
        for i, n in enumerate((*LEVEL_VALUES, *extra_levels)):
            specs.append(_single(level(target, n), LEVEL_STYLES[i % 4], f"s{i % 4}"))
        for d in ("up", "down"):
            specs += [_single(adjust(target, d, a)) for a in AMOUNT_JA]
            specs += [_single(adjust(target, d, by=n)) for n in BY_VALUES]
        specs.append(Spec(f"v1.single.out_of_range.{target}", "single", (level(target, 100),),
                          f"ロボットに「{TARGET_JA[target]}を最大より大きい値（例: 150、200%）に"
                          "する」ように頼む", "100 より大きい数字を必ず入れる"))  # fmt: skip
    return specs


MULTI_POOL_V1 = [
    look("right", degrees=45), look("up", degrees=30), turn("left", "slight"), look("center"),
    _count("nod", 2), _count("shake", 1), bow(), expression("angry"), expression("happy"),
    led("blue"), led("off"), level("volume", 50), adjust("volume", "up"),
    level("brightness", 30), adjust("brightness", "down", "slight"),
]  # fmt: skip
_MOVES = ("look", "turn")


def multi_specs() -> list[Spec]:
    specs = []
    for a, b in itertools.permutations(MULTI_POOL_V1, 2):
        if a["name"] in _MOVES and b["name"] in _MOVES and look("center") not in (a, b):
            continue  # two head moves only when one of them returns to center (as in v0)
        meaning = (f"ロボットに、まず「{describe(a)}」、そのあと「{describe(b)}」の順で、"
                   "2つの動作を頼む（順序が分かるように）")  # fmt: skip
        specs.append(Spec(f"v1.multi.{_id(a)}+{_id(b)}", "multi_action", (a, b), meaning))
    return specs


NEGATABLE_V1 = [
    turn("right", "slight"), look("right", degrees=45), _count("shake", 1), bow(),
    expression("angry"), expression("sleepy"), expression("doubt"), led("red"), led("off"),
    level("volume", 0), adjust("volume", "up"), adjust("brightness", "down"),
    level("brightness", 100),
]  # fmt: skip


def negation_specs() -> list[Spec]:
    return [
        Spec(f"v1.negation.{_id(c)}", "negation", (),
             f"ロボットに「{describe(c)}」ことを、しないように頼む（否定の依頼）")  # fmt: skip
        for c in NEGATABLE_V1
    ]


CORRECTIONS_V1 = [
    (led("red"), led("blue")),
    (led("blue"), led("off")),
    (level("volume", 50), level("volume", 30)),
    (look("right", degrees=30), look("right", degrees=45)),
    (adjust("volume", "up"), adjust("volume", "down")),
    (_count("nod", 1), _count("shake", 1)),
    (expression("happy"), expression("angry")),
    (look("left", "normal"), turn("left", "slight")),
]


def correction_specs() -> list[Spec]:
    specs = [
        Spec(f"v1.correction.{_id(w)}->{_id(r)}", "correction", (r,),
             f"「{describe(w)}」ではなく「{describe(r)}」ように頼む（言い直しや訂正）")  # fmt: skip
        for w, r in CORRECTIONS_V1
    ]
    for neg, pos in [(led("red"), _count("nod", 1)), (level("volume", 80), expression("happy")),
                     (_count("shake", 1), bow())]:  # fmt: skip
        specs.append(Spec(f"v1.correction.partial.{_id(neg)}->{_id(pos)}", "correction", (pos,),
                          f"「{describe(neg)}」ことはしないで、「{describe(pos)}」ことだけを頼む"))
    return specs


def no_action_specs() -> list[Spec]:
    return [Spec(f"v1.no_action.{k}", "no_action", (), f"ロボットに対する、{v}")
            for k, v in CONFUSER_TOPICS.items()]  # fmt: skip


def all_specs_v1(seed: int = 20261002) -> list[Spec]:
    rng = random.Random(seed)
    return (single_specs(rng) + multi_specs() + negation_specs() + correction_specs()
            + no_action_specs())  # fmt: skip


def paraphrase_specs(seed: int = 20261003) -> list[Spec]:
    """Head moves with numbers and amounts, for the paraphrases of the Stack-chan set."""
    rng = random.Random(seed)
    return [s for s in single_specs(rng) if s.label[0]["name"] in _MOVES]
```

Step 1 の test に、`describe` の `adjust` の3つの形も足す。

```python
def test_describe_adjust() -> None:
    assert describe({"name": "adjust_volume", "arguments": {"direction": "up", "amount": "slight"}}) == (
        "スピーカーの音量を少しだけ上げる")
    assert describe({"name": "adjust_brightness", "arguments": {"direction": "down", "amount": "slight"}}) == (
        "画面を少しだけ暗くする")
    assert describe({"name": "adjust_brightness", "arguments": {"direction": "down", "by": 10}}) == (
        "画面の明るさを10だけ下げる")
```

- [ ] **Step 4: `prompts.py` を v1 にする**

- `PROMPT_VERSION = "action-v1.0"`
- `ROBOT = "首を左右・上下・斜めに動かせて、画面に表情を出せて、台座のLEDライトの色、スピーカーの音量、画面の明るさを変えられる、小さな卓上ロボット"`
- `_default_requirements` と `requirements` の no_action の条件を `"首を動かす、表情を変える、うなずく、首を振る、お辞儀、LEDライト・音量・画面の明るさの変更を、ロボットに頼む文にはしない"` にする。
- `_default_requirements` の call ごとの条件に、次を足す（v0 の look の条件は `"degrees" not in args` のときだけ適用する）。

```python
        if call["name"] == "look" and "degrees" in args:
            reqs.append(f"角度（{args['degrees']}度）を必ず入れる")
        if call["name"] == "look" and args.get("direction") != "center":
            reqs.append("「もう」「さらに」「もっと」「そこから」のような、今の向きを基準にする言葉は入れない")
        if call["name"] == "turn":
            reqs.append("「もう少し」「さらに」「もっと」「そこから」のように、今の向きから動かすことが分かる言葉を必ず入れる")
            if "degrees" in args:
                reqs.append(f"角度（{args['degrees']}度）を必ず入れる")
        if call["name"] == "shake":
            reqs.append("首を横に振る動きだと分かる言い方にする（うなずく動きと混ぜない）")
            if args["count"] >= 2:
                reqs.append(f"首を振る回数（{args['count']}回）が分かるようにする")
        if call["name"] == "set_led":
            reqs.append("「LED」「ライト」「内蔵ライト」「光」のどれかを使う。部屋の照明や電気の話にはしない")
        if call["name"] in ("set_volume", "adjust_volume"):
            reqs.append("「音量」「ボリューム」「音」のどれかを使う。テレビなど、ほかの機器の音の話にはしない")
        if call["name"] in ("set_brightness", "adjust_brightness"):
            reqs.append("「画面」「明るさ」「明るく」「暗く」のどれかを使う。部屋の明るさの話にはしない")
        if call["name"] in ("set_volume", "set_brightness") and args["level"] not in (0, 100):
            reqs.append(f"値（{args['level']}）が分かるように書く")
        if call["name"] in ("adjust_volume", "adjust_brightness") and "by" in args:
            reqs.append(f"変える量（{args['by']}）を必ず入れる")
```

- `VERIFY_SYSTEM` を次に置き換える。

```python
VERIFY_SYSTEM = """あなたは、卓上ロボットへの日本語や英語の発話を、ロボットの動作の JSON に変換する担当者です。

使える動作は次の11個だけです。
- look: 正面を基準に首を向ける（絶対）。direction は left / right / up / down / up_left / up_right / down_left / down_right / center。amount（slight / normal / large）か degrees（1〜180 の整数）のどちらか一方
- turn: 今の向きから首を動かす（相対）。direction は center 以外。amount か degrees のどちらか一方
- nod: うなずく。count は 1〜5
- shake: 首を横に振る。count は 1〜5
- bow: お辞儀する。arguments は {}
- set_expression: 表情を変える。expression は happy / sad / surprised / neutral / angry / sleepy / doubt
- set_led: 台座のLEDライトの色。color は red / orange / yellow / green / light_blue / blue / purple / pink / white / off
- set_volume: スピーカーの音量。level は 0〜100
- adjust_volume: 音量を上げ下げする。direction は up / down、amount か by（1〜100）のどちらか一方
- set_brightness: 画面の明るさ。level は 0〜100
- adjust_brightness: 画面の明るさを上げ下げする。direction は up / down、amount か by のどちらか一方

規則:
- 発話が頼んでいる動作だけを、頼まれた順に、最大2個出力する。
- 否定された動作（〜しないで、〜ではなく）は出力しない。頼んでいる動作がなければ [] を出力する。
- 雑談、質問、あいさつ、気持ちの報告、ロボットにできない依頼、何をすべきか分からない依頼は [] を出力する。
- 部屋の照明・電気、エアコン、テレビなど、ロボット以外の機器の操作は [] を出力する。
- 「もう」「さらに」「もっと」「そこから」など、今の向きを基準にする言葉があれば turn、なければ look。
- 角度が数字で言われたら degrees（45、４５、四十五、45° はすべて 45）。数字がなければ amount。
- 「少し」「ちょっと」などは slight、「大きく」「思いっきり」などは large、それ以外は normal。
- 正面や真ん中を向くときは look の direction を center、amount を normal にする。
- 笑う・嬉しそう → happy、悲しそう・泣く → sad、驚く → surprised、真顔・普通の顔 → neutral、怒る → angry、眠そう → sleepy、不思議そう・困った顔 → doubt。
- うなずく回数、首を振る回数の指定がなければ count は 1。
- LED・ライトを消す → set_led の off。消音・ミュート → set_volume の 0。「半分」は 50、「最大」「いちばん大きく」は 100。100 を超える値は 100。
- 「音量を上げて」「明るくして」のように値がなければ adjust_volume / adjust_brightness（量の言葉がなければ amount は normal）。
- JSON の配列だけを出力する。"""
```

- [ ] **Step 5: MASSIVE の音量の intent を外す**

`massive.py` に `VOLUME_INTENTS = ("audio_volume_up", "audio_volume_down", "audio_volume_mute", "audio_volume_other")` を足し、`load` で `r["intent"] not in VOLUME_INTENTS` も条件にする（v1 では音量の依頼は動作なので、`[]` の候補にしない。部屋の照明の `iot_hue_*` は `[]` のまま残す）。docstring に1行足す。

- [ ] **Step 6: test が通ることを確かめる**

Run: `uv run pytest tests/test_data_specs_v1.py tests/test_data_specs_checks.py tests/test_data_generate.py tests/test_data_build.py -q`
Expected: PASS。v0 の spec の test が `PROMPT_VERSION` や `ROBOT` の文言に依存して失敗する場合は、v1 の文言に合わせる。

- [ ] **Step 7: Commit**

```bash
git add src/jtalm/data/specs_v1.py src/jtalm/data/prompts.py src/jtalm/data/massive.py tests/test_data_specs_v1.py
git commit -m "data: v1 specs (diagonals, degrees in three notations, turn, shake, bow, new faces, LED, volume, brightness, out-of-range, device confusers) and the v1 verifier prompt"
```

---

### Task 9: 生成の phase を足す（spec_set v1、reverify）

**Files:**
- Modify: `src/jtalm/data/generate.py`
- Modify: `tests/test_data_generate.py`

**Interfaces:**
- Consumes: `all_specs_v1`、`paraphrase_specs`（Task 8）
- Produces:
  - config の `"spec_set"` に `"v1"` と `"v1_paraphrase"` を足す（`sample_requests` に渡す spec の集合が変わるだけ）。
  - phase `reverify`: `--input FILE ...`（EvalCase の JSONL）を読み、各行 `{"id", "text", "expected", "category", "source", "file"}` を Qwen3 で検証し、`<out>/reverify_raw.jsonl` に `verified` を足して書く。

- [ ] **Step 1: 失敗する test を書く**

`tests/test_data_generate.py` に足す（既存の test の、`Generator` を偽物に差し替える書き方に合わせる。`chat_json` を `lambda *a, **k: [{"name": "bow", "arguments": {}}]` にした偽物を使う）。

```python
def test_reverify_reads_cases_and_keeps_their_labels(tmp_path, monkeypatch) -> None:
    from jtalm.data import generate

    src = tmp_path / "train.jsonl"
    src.write_text('{"id": "t-1", "category": "single", "prompt": "お辞儀して", '
                   '"expected": [], "language": "ja"}\n', encoding="utf-8")
    monkeypatch.setattr(generate.Generator, "chat_json",
                        lambda self, *a, **k: [{"name": "bow", "arguments": {}}])
    cfg = tmp_path / "c.json"
    cfg.write_text('{"verifier": {"served_name": "qwen", "hf_id": "Qwen/x"}, "top_p": 1, '
                   '"max_tokens": 10, "train_generator": {"served_name": "qwen", "hf_id": "Qwen/x"}, '
                   '"eval_generator": {"served_name": "l", "hf_id": "l"}}', encoding="utf-8")
    import argparse
    summary = generate.run(argparse.Namespace(phase="reverify", config=str(cfg), base_url="x",
                                              workers=1, out=str(tmp_path / "o"), input=[str(src)]))
    rows = [json.loads(x) for x in (tmp_path / "o/reverify_raw.jsonl").read_text("utf-8").splitlines()]
    assert summary["rows"] == 1
    assert rows[0]["id"] == "t-1" and rows[0]["expected"] == []
    assert rows[0]["verified"] == [{"name": "bow", "arguments": {}}]
    assert rows[0]["file"] == str(src)


def test_spec_set_v1_uses_the_v1_specs() -> None:
    import random

    from jtalm.data.generate import _specs_for

    specs = _specs_for({"spec_set": "v1", "per_request": 8}, {"single": 16}, random.Random(0))
    assert all(s.id.startswith("v1.single.") for s in specs) and len(specs) == 2
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_data_generate.py -q`
Expected: FAIL（`reverify` が PHASES にない、`_specs_for` がない）

- [ ] **Step 3: `generate.py` を直す**

`PHASES` に `"reverify"` を足す。`generate_sentences` の spec の選び方を関数に切り出す。

```python
from jtalm.data.specs_v1 import all_specs_v1, paraphrase_specs


def _specs_for(cfg: dict, quota: dict, rng: random.Random) -> list[Spec]:
    n = cfg["per_request"]
    spec_set = cfg.get("spec_set")
    if spec_set == "focus":
        return sample_by_slice(focus_specs(), cfg["slice_quota"], n, rng)
    if spec_set == "v1":
        return sample_requests(all_specs_v1(), quota, n, rng)
    if spec_set == "v1_paraphrase":
        return sample_requests(paraphrase_specs(), quota, n, rng)
    return sample_requests(all_specs(), quota, n, rng)
```

`generate_sentences` の `if cfg.get("spec_set") == "focus": ... else: ...` を `specs = _specs_for(cfg, quota, rng)` に置き換える。`phase_eval_gen` の pair と英語の生成は、`cfg["eval_pairs"]` と `cfg["eval_english"]` が 0 なら何も作らない（既存のコードのまま）。

reverify の phase を足す。

```python
def phase_reverify(gen: Generator, name: str, inputs: list[str], workers: int):
    rows = []
    for path in inputs:
        for line in Path(path).read_text("utf-8").splitlines():
            if line.strip():
                case = json.loads(line)
                rows.append({"id": case["id"], "text": case["prompt"],
                             "expected": case["expected"], "category": case["category"],
                             "language": case.get("language", "ja"),
                             "source": case.get("source"), "file": path})  # fmt: skip
    return phase_verify(gen, name, rows, workers)
```

`run` に分岐を足す（verifier は config の `"verifier"`）。

```python
    elif args.phase == "reverify":
        verifier_cfg = cfg["verifier"]
        gen = Generator(args.base_url, verifier_cfg["served_name"], cfg)
        rows, failures = phase_reverify(gen, verifier_cfg["hf_id"], args.input, args.workers)
        stats = {"reverify_failures": failures}
        _write(out / "reverify_raw.jsonl", rows)
```

`main` に `parser.add_argument("--input", nargs="*", default=[], help="case files for reverify")` を足す。

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run pytest tests/test_data_generate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jtalm/data/generate.py tests/test_data_generate.py
git commit -m "generate: spec sets v1 / v1_paraphrase and a reverify phase (Qwen3 re-parses existing cases under schema v1)"
```

---

### Task 10: スタックチャン実例セットの素材と組み立て

**Files:**
- Create: `datasets/action/stackchan_v1/sources.jsonl`（git では追跡しない。他の評価セットと同じ）
- Create: `datasets/manifests/action_stackchan_v1.json`（追跡する。Step 5 で生成）
- Create: `src/jtalm/data/stackchan_eval.py`
- Create: `tests/test_stackchan_eval.py`

**Interfaces:**
- Consumes: `reverify` の結果（`reverify_raw.jsonl`。`file` が `sources.jsonl` の行）、`eval-verify` の結果（`eval_raw.jsonl`、`v1_paraphrase` の言い換え）
- Produces: `stackchan_eval.build(sources, reverified, paraphrase_raw, overrides, out_dir, n_paraphrase=40, seed=0) -> dict`。`out_dir/eval.jsonl`（EvalCase。`source` は `verbatim:<url>` か `user` か `paraphrase:<generator>`、`category` は正解から決める）と `out_dir/review.md`（利用者が確認する表）を書く。`overrides`（`{"id": ..., "expected": [...]}` の JSONL）の正解で上書きする。

- [ ] **Step 1: 実例を `sources.jsonl` に書き写す**

調査で原文と照合した発話（会話の記録にある表の #1〜#60 のうち、`{N}` のような型ではなく文そのものが書かれているもの）を、1文1行で書く。1つの行に「／」で並んでいる文は、別々の行にする。利用者の4文も入れる。各行の形:

```json
{"id": "sc-001", "text": "音量を 80% に設定して。", "source_url": "https://docs.m5stack.com/ja/StackChan", "license": "none stated (M5Stack docs)", "kind": "verbatim"}
{"id": "sc-u1", "text": "LEDライトの色を青にして", "source_url": "user", "license": "user", "kind": "user"}
```

原文にない文を足したり、文を直したりしない（Claude が文を書かない規則。言い換えは llm-jp が書く）。発話の前の「（スピーカー）」のような分類の注記は、原文の発話の一部ではないので除く。

- [ ] **Step 2: 失敗する test を書く**

`tests/test_stackchan_eval.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
import json

from jtalm.data.stackchan_eval import build
from jtalm.eval.cases import load_cases


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def test_build_merges_sources_paraphrases_and_overrides(tmp_path) -> None:
    src = tmp_path / "sources.jsonl"
    write(src, [{"id": "sc-001", "text": "左に頭を回して。", "source_url": "u", "license": "MIT",
                 "kind": "verbatim"},
                {"id": "sc-002", "text": "寝室のライトをつけて。", "source_url": "u", "license": "MIT",
                 "kind": "verbatim"}])  # fmt: skip
    look = [{"name": "look", "arguments": {"direction": "left", "amount": "normal"}}]
    rev = tmp_path / "rev.jsonl"
    write(rev, [{"id": "sc-001", "file": str(src), "verified": look},
                {"id": "sc-002", "file": str(src), "verified": look}])  # fmt: skip
    para = tmp_path / "para.jsonl"
    write(para, [{"spec_id": "v1.single.turn.right.slight", "category": "single",
                  "label": [{"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}],
                  "text": "もうちょい右", "language": "ja", "generator": "llm-jp/x",
                  "verified": [{"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}]}])
    over = tmp_path / "over.jsonl"
    write(over, [{"id": "sc-002", "expected": []}])
    out = tmp_path / "out"
    stats = build(src, rev, para, over, out, n_paraphrase=40, seed=0)
    cases = {c.id: c for c in load_cases(out / "eval.jsonl")}
    assert cases["sc-001"].expected == look and cases["sc-001"].source == "verbatim:u"
    assert cases["sc-002"].expected == [] and cases["sc-002"].category == "no_action"
    assert len([c for c in cases.values() if c.source.startswith("paraphrase:")]) == 1
    assert stats == {"verbatim": 2, "user": 0, "paraphrase": 1, "overridden": 1}
    assert "寝室のライトをつけて。" in (out / "review.md").read_text("utf-8")
```

- [ ] **Step 3: test が失敗することを確かめる**

Run: `uv run pytest tests/test_stackchan_eval.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 4: `stackchan_eval.py` を書く**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""The Stack-chan everyday-phrasing evaluation set v1 (spec 5.3).

    uv run python -m jtalm.data.stackchan_eval --raw artifacts/raw1 --out datasets/action/stackchan_v1

Verbatim utterances from public Stack-chan projects and the user's own requests
(``sources.jsonl``) are labeled by Qwen3 under schema v1 (the ``reverify`` phase); paraphrases
of head moves (sparse on the web) are written by llm-jp and kept when Qwen3 agrees with their
spec. The user reviews every label in ``review.md``; corrections go to ``overrides.jsonl``.
Never used for training or model selection.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

from jtalm.action.schema import canonicalize, to_json
from jtalm.data.build import _keep
from jtalm.data.checks import normalize
from jtalm.eval.cases import EvalCase, write_cases


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]


def _category(expected: list) -> str:
    if not expected:
        return "no_action"
    return "single" if len(expected) == 1 else "multi_action"


def build(sources: Path, reverified: Path, paraphrase_raw: Path, overrides: Path, out_dir: Path,
          n_paraphrase: int = 40, seed: int = 0) -> dict:  # fmt: skip
    labels = {r["id"]: r.get("verified") for r in _read(reverified)
              if Path(r["file"]).resolve() == sources.resolve()}  # fmt: skip
    fixed = {r["id"]: r["expected"] for r in _read(overrides)}
    cases: list[EvalCase] = []
    stats = {"verbatim": 0, "user": 0, "paraphrase": 0, "overridden": 0}
    for row in _read(sources):
        expected = fixed.get(row["id"], labels.get(row["id"]))
        if not isinstance(expected, list):
            raise ValueError(f"no label for {row['id']}; add it to {overrides}")
        stats["overridden"] += row["id"] in fixed
        stats[row["kind"]] += 1
        source = "user" if row["kind"] == "user" else f"verbatim:{row['source_url']}"
        cases.append(EvalCase(id=row["id"], prompt=row["text"], expected=canonicalize(expected),
                              category=_category(expected), source=source))  # fmt: skip
    kept = [r for r in _read(paraphrase_raw) if _keep(r)[0]]
    random.Random(seed).shuffle(kept)
    for r in kept[:n_paraphrase]:
        text = normalize(r["text"])
        digest = hashlib.sha1(f"stackchan:{text}".encode()).hexdigest()[:12]
        expected = canonicalize(r["label"])
        cases.append(EvalCase(id=f"sc-p-{digest}", prompt=text, expected=expected,
                              category=_category(expected), source=f"paraphrase:{r['generator']}"))
        stats["paraphrase"] += 1
    out_dir.mkdir(parents=True, exist_ok=True)
    write_cases(out_dir / "eval.jsonl", cases)
    lines = ["| id | 入力 | 正解 | 出典 |", "|---|---|---|---|"]
    lines += [f"| {c.id} | {c.prompt} | `{to_json(c.expected)}` | {c.source} |" for c in cases]
    (out_dir / "review.md").write_text("\n".join(lines) + "\n", "utf-8")
    return stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True, help="the job's artifacts directory")
    p.add_argument("--out", type=Path, default=Path("datasets/action/stackchan_v1"))
    args = p.parse_args()
    stats = build(args.out / "sources.jsonl", args.raw / "reverify1/reverify_raw.jsonl",
                  args.raw / "raw1_paraphrase/eval_raw.jsonl", args.out / "overrides.jsonl",
                  args.out)  # fmt: skip
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: test が通ることを確かめる**

Run: `uv run pytest tests/test_stackchan_eval.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/jtalm/data/stackchan_eval.py tests/test_stackchan_eval.py
git commit -m "Stack-chan everyday-phrasing eval set v1: verbatim public utterances + the user's requests (Qwen3 labels, user review) + llm-jp paraphrases of head moves"
```

（`sources.jsonl` は追跡しない。manifest は Task 12 で書く。）

---

### Task 11: データ v1.0 を組み立てる（引き継ぎ、付け直し、新しい文、eval v3）

**Files:**
- Create: `src/jtalm/data/build_v1.py`
- Create: `tests/test_data_build_v1.py`

**Interfaces:**
- Consumes: `reverify_raw.jsonl`（Task 9）、`train_raw.jsonl` / `eval_raw.jsonl`（各書き手）、`build._filter`、`build._case`、`uses_v1_only`（Task 1）
- Produces:
  - `relabel(rows: list[dict]) -> tuple[list[EvalCase], list[dict], Counter]`: 引き継ぐ case（正解は元のままか v1 の付け直し）、付け直した行の一覧、落とした理由の数。
  - 規則: v1 の検証結果 == 元の正解 → 元のまま残す。違っていて、検証結果が `uses_v1_only` → 検証結果を新しい正解にして残す（`source` に `+relabel:v1` を付ける）。それ以外（検証役が v0 の範囲で違う答えを出した）→ 落とす。
  - CLI が `datasets/action/v1.0/{train,val}.jsonl`、`datasets/action/eval_v3/eval.jsonl`、`datasets/action/relabel_v1/<set>.jsonl` と `changes.md`、`datasets/manifests/action_v1.0.json` を書く。

- [ ] **Step 1: 失敗する test を書く**

`tests/test_data_build_v1.py`:

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
from jtalm.data.build_v1 import relabel

LOOK = [{"name": "look", "arguments": {"direction": "left", "amount": "large"}}]
DEG = [{"name": "look", "arguments": {"direction": "left", "degrees": 90}}]
TURN = [{"name": "turn", "arguments": {"direction": "right", "amount": "slight"}}]


def row(i: str, text: str, expected: list, verified: list, category: str = "single") -> dict:
    return {"id": i, "text": text, "expected": expected, "verified": verified,
            "category": category, "language": "ja", "source": "synthetic:x", "file": "train.jsonl"}


def test_relabel_keeps_agreeing_rows_and_relabels_only_into_v1() -> None:
    rows = [
        row("a", "左を大きく向いて", LOOK, LOOK),
        row("b", "左に90度ターンして", LOOK, DEG),
        row("c", "もう少し右", [{"name": "look", "arguments": {"direction": "right", "amount": "slight"}}], TURN),
        row("d", "今日は晴れ", [], LOOK, "no_action"),
        row("e", "音量を上げて", [], [{"name": "adjust_volume", "arguments": {"direction": "up", "amount": "normal"}}], "no_action"),
        row("f", "壊れた行", LOOK, None),
    ]  # fmt: skip
    cases, changed, dropped = relabel(rows)
    by_id = {c.id: c for c in cases}
    assert by_id["a"].expected == LOOK and by_id["a"].source == "synthetic:x"
    assert by_id["b"].expected == DEG and by_id["b"].source.endswith("+relabel:v1")
    assert by_id["c"].expected == TURN
    assert by_id["e"].category == "single"
    assert "d" not in by_id and "f" not in by_id
    assert [r["id"] for r in changed] == ["b", "c", "e"]
    assert dropped == {"verifier_disagrees_v0": 1, "verify_failed": 1}
```

- [ ] **Step 2: test が失敗することを確かめる**

Run: `uv run pytest tests/test_data_build_v1.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: `build_v1.py` を書く**

```python
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""Assemble data v1.0, evaluation set v3, and the v1 labels of the older evaluation sets.

    uv run python -m jtalm.data.build_v1 --raw artifacts/gen_action_v1

1. Inherited rows (data v0.5.1 train/val, re-parsed by Qwen3 under schema v1, ``reverify``):
   kept with their label when Qwen3 agrees; relabeled when Qwen3's answer needs schema v1
   (degrees, turn, a new tool...); dropped otherwise.
2. New sentences of the v1 writers: kept when Qwen3's parse equals the spec label (as in v0).
3. Evaluation set v3 (llm-jp writes, Qwen3 verifies): same rule as 2.
4. v0 eval, human v1 and eval v2: relabeled by rule 1 into datasets/action/relabel_v1/, with a
   list of every change for the user's review (changes.md).
Duplicates and any overlap with an evaluation set are removed from the training data.
"""

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from jtalm.action.schema import canonicalize, to_json, uses_v1_only
from jtalm.data.build import _case, _filter, _load
from jtalm.data.checks import dedup_key
from jtalm.eval.cases import EvalCase, load_cases, write_cases

VAL_FRACTION = 0.05
V1_WRITER_NAMES = ("qwen", "abeja", "calm3", "elyza", "nemoja")  # configs/action_v1_<name>.json
INHERITED = ("datasets/action/v0.5.1/train.jsonl", "datasets/action/v0.5.1/val.jsonl")
OLD_EVAL = {
    "v0_eval": "datasets/action/v0/eval.jsonl",
    "human_v1": "datasets/action/human_v1/eval.jsonl",
    **{f"eval_v2_{p.stem}": p.as_posix() for p in sorted(Path("datasets/action/eval_v2").glob("*.jsonl"))},
}  # fmt: skip


def _category(expected: list, old: str) -> str:
    if expected and old in ("no_action", "negation"):
        return "single" if len(expected) == 1 else "multi_action"
    return old


def relabel(rows: list[dict]) -> tuple[list[EvalCase], list[dict], Counter]:
    cases, changed, dropped = [], [], Counter()
    for r in rows:
        verified = r.get("verified")
        if not isinstance(verified, list):
            dropped["verify_failed"] += 1
            continue
        try:
            old, new = canonicalize(r["expected"]), canonicalize(verified)
        except (AttributeError, TypeError):
            dropped["verify_failed"] += 1
            continue
        source = r.get("source") or ""
        if new != old:
            if not uses_v1_only(new):
                dropped["verifier_disagrees_v0"] += 1
                continue
            changed.append({**r, "old": old, "new": new})
            source += "+relabel:v1"
        cases.append(EvalCase(id=r["id"], prompt=r["text"], expected=new,
                              category=_category(new, r["category"]),
                              language=r.get("language", "ja"), source=source))  # fmt: skip
    return cases, changed, dropped


def _by_file(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(Path(r["file"]).as_posix(), []).append(r)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--out", type=Path, default=Path("datasets/action/v1.0"))
    p.add_argument("--eval-out", type=Path, default=Path("datasets/action/eval_v3"))
    p.add_argument("--relabel-out", type=Path, default=Path("datasets/action/relabel_v1"))
    p.add_argument("--manifest", type=Path, default=Path("datasets/manifests/action_v1.0.json"))
    p.add_argument("--seed", type=int, default=20261002)
    args = p.parse_args()

    rev = _by_file([json.loads(x) for x in
                    (args.raw / "reverify1/reverify_raw.jsonl").read_text("utf-8").splitlines() if x])  # fmt: skip
    stats: dict = {"created": datetime.now(UTC).isoformat(timespec="seconds")}

    # 4. older evaluation sets (labels for the v1 evaluation; the user reviews changes.md)
    args.relabel_out.mkdir(parents=True, exist_ok=True)
    review = ["| set | id | 入力 | v0 の正解 | v1 の正解 |", "|---|---|---|---|---|"]
    eval_keys: set[str] = set()
    for name, path in OLD_EVAL.items():
        cases, changed, dropped = relabel(rev.get(path, []))
        kept_ids = {c.id for c in cases}
        # keep the v0 label of rows whose v1 parse was dropped: they stay comparable with v0
        cases += [c for c in load_cases(path) if c.id not in kept_ids]
        write_cases(args.relabel_out / f"{name}.jsonl", cases)
        review += [f"| {name} | {r['id']} | {r['text']} | `{to_json(r['old'])}` | `{to_json(r['new'])}` |"
                   for r in changed]  # fmt: skip
        stats[f"relabel_{name}"] = {"n": len(cases), "changed": len(changed), **dropped}
        eval_keys |= {dedup_key(c.prompt) for c in cases}
    (args.relabel_out / "changes.md").write_text("\n".join(review) + "\n", "utf-8")

    # 3. evaluation set v3
    seen_eval: set[str] = set()
    ev_stats: Counter = Counter()
    ev_rows = _filter(_load(sorted(args.raw.glob("raw1_eval")), "eval_raw.jsonl"), seen_eval, ev_stats)
    ev3 = [_case(r, "ev3") for r in ev_rows]
    args.eval_out.mkdir(parents=True, exist_ok=True)
    write_cases(args.eval_out / "eval.jsonl", ev3)
    stats["eval_v3"] = {"n": len(ev3), **ev_stats}
    sc = Path("datasets/action/stackchan_v1/eval.jsonl")
    eval_keys |= {dedup_key(c.prompt) for c in ev3}
    if sc.exists():
        eval_keys |= {dedup_key(c.prompt) for c in load_cases(sc)}

    # 1. inherited train/val and 2. new sentences
    train, val = [], []
    seen: set[str] = set(eval_keys)
    for path, split in zip(INHERITED, (train, val), strict=True):
        cases, changed, dropped = relabel(rev.get(path, []))
        kept = [c for c in cases if dedup_key(c.prompt) not in seen]
        seen |= {dedup_key(c.prompt) for c in kept}
        split.extend(kept)
        stats[f"inherited_{Path(path).stem}"] = {"n": len(kept), "relabeled": len(changed),
                                                 "overlap_or_dup": len(cases) - len(kept), **dropped}  # fmt: skip
    new_stats: Counter = Counter()
    writer_dirs = [args.raw / f"raw1_{w}" for w in V1_WRITER_NAMES if (args.raw / f"raw1_{w}").is_dir()]
    new_rows = _filter(_load(writer_dirs, "train_raw.jsonl"), seen, new_stats)
    rng = random.Random(args.seed)
    rng.shuffle(new_rows)
    n_val = round(len(new_rows) * VAL_FRACTION)
    val += [_case(r, "val") for r in new_rows[:n_val]]
    train += [_case(r, "train") for r in new_rows[n_val:]]
    stats["new"] = {"n": len(new_rows), **new_stats}

    args.out.mkdir(parents=True, exist_ok=True)
    write_cases(args.out / "train.jsonl", train)
    write_cases(args.out / "val.jsonl", val)
    for name, cases in (("train", train), ("val", val)):
        stats[name] = {"n": len(cases), "by_category": dict(Counter(c.category for c in cases)),
                       "sha256": hashlib.sha256((args.out / f"{name}.jsonl").read_bytes()).hexdigest()}  # fmt: skip
    args.manifest.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k in ("train", "val", "new", "eval_v3")},
                     ensure_ascii=False))  # fmt: skip


if __name__ == "__main__":
    main()
```

`_load(dirs, name)` は `build.py` の既存の関数（各 dir の `name` を読む）。書き手の dir は `V1_WRITER_NAMES` で選ぶ（`raw1_eval` と `raw1_paraphrase` は評価用なので学習データに入れない）。名前は Task 12 の job の出力 dir（`raw1_<name>`）と同じ。

- [ ] **Step 4: test が通ることを確かめる**

Run: `uv run pytest tests/test_data_build_v1.py tests/test_data_build.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jtalm/data/build_v1.py tests/test_data_build_v1.py
git commit -m "build_v1: inherit v0.5.1 under schema v1 (keep, relabel into v1, or drop), new v1 sentences, eval v3, relabeled older eval sets with a change list"
```

---

### Task 12: データ生成の job（vast.ai）と tokenizer v1

**Files:**
- Create: `configs/action_v1_{qwen,abeja,calm3,elyza,nemoja}.json`、`configs/eval_v3.json`、`configs/stackchan_v1_paraphrase.json`
- Modify: `src/jtalm/infra/jobs.py`
- Modify: `src/jtalm/model/tokenizer.py`
- Create（生成物、追跡しない）: `artifacts/gen_action_v1/`、`datasets/action/{v1.0,eval_v3,relabel_v1,stackchan_v1}/`、`tokenizer/out/action_v1_sp2048.model`
- Create（追跡する）: `datasets/manifests/action_v1.0.json`、`datasets/manifests/action_stackchan_v1.json`、`datasets/manifests/tokenizer_action_v1.json`

**Interfaces:**
- Produces: `jobs.GEN_ACTION_V1`（job 名 `gen_action_v1`）、`jobs.TOKENIZER_V1 = "tokenizer/out/action_v1_sp2048.model"`、`jobs.ACTION_DATA_V1 = "datasets/action/v1.0"`

- [ ] **Step 1: config を書く**

`configs/action_v1_qwen.json`（他の書き手は `served_name` と `hf_id`、`license`、`seed` だけを変える。seed は qwen 20261002、abeja 20261012、calm3 20261022、elyza 20261032、nemoja 20261042）:

```json
{
  "dataset_version": "action-v1.0",
  "seed": 20261002,
  "per_request": 8,
  "temperature": 0.9,
  "top_p": 0.95,
  "max_tokens": 900,
  "prompt_version": "action-v1.0",
  "train_styles": "v0.3",
  "spec_set": "v1",
  "train_generator": {"served_name": "qwen", "hf_id": "Qwen/Qwen3-30B-A3B-Instruct-2507", "license": "Apache-2.0"},
  "eval_generator": {"served_name": "llmjp", "hf_id": "llm-jp/llm-jp-3.1-13b-instruct4", "license": "Apache-2.0"},
  "verifier": {"served_name": "qwen", "hf_id": "Qwen/Qwen3-30B-A3B-Instruct-2507", "license": "Apache-2.0"},
  "train_verifier": "verifier",
  "train_quota": {"single": 4000, "multi_action": 3000, "negation": 1200, "correction": 1000, "no_action": 1200},
  "eval_quota": {},
  "eval_pairs": 0,
  "eval_english": 0,
  "massive": {"train_negatives": 0, "eval_negatives": 0}
}
```

`configs/eval_v3.json`: 上と同じ形で `"train_quota": {}`、`"eval_quota": {"single": 1600, "multi_action": 500, "negation": 300, "correction": 300, "no_action": 500}`、seed 20261102。

`configs/stackchan_v1_paraphrase.json`: `"spec_set": "v1_paraphrase"`、`"eval_quota": {"single": 120}`、seed 20261202。

5人の書き手で約 52,000 文、検証で約 60% が残ると約 31,000 文が新しく増える見込み。

- [ ] **Step 2: job を足す**

`jobs.py` に足し、`JOBS` に登録する。

```python
# Data v1.0 (schema v1): llm-jp writes eval v3 and the Stack-chan paraphrases; five writers
# write the new training sentences; Qwen3 verifies everything and re-parses the inherited
# v0.5.1 data and the older evaluation sets under schema v1 (reverify).
V1_WRITERS = [w for w in V04_WRITERS if w[0] in ("abeja", "calm3", "elyza", "nemoja")]
V1_RAW = "artifacts/gen_action_v1"
STACKCHAN_SOURCES = "datasets/action/stackchan_v1/sources.jsonl"
V1_REVERIFY_INPUTS = [
    "datasets/action/v0.5.1/train.jsonl", "datasets/action/v0.5.1/val.jsonl",
    "datasets/action/v0/eval.jsonl", "datasets/action/human_v1/eval.jsonl",
    *[f"datasets/action/eval_v2/{s}.jsonl" for s in (
        "amount_words", "center_phrasing", "correction", "english", "fragments", "long_preface",
        "negation_forms", "numbers", "order_words", "orthography", "question_forms",
        "unexecutable")],
]  # fmt: skip


def _v1_steps() -> list[str]:
    steps = ["nvidia-smi > artifacts/nvidia_smi.txt", "df -h /", sync(), f"mkdir -p {V1_RAW}"]
    steps += [
        start_vllm(EVAL_MODEL, gpu_mem=0.9, max_len=4096, extra="--served-model-name llmjp"),
        generate("eval-gen", "configs/eval_v3.json", f"{V1_RAW}/raw1_eval"),
        generate("eval-gen", "configs/stackchan_v1_paraphrase.json", f"{V1_RAW}/raw1_paraphrase"),
        f"{STOP_VLLM}; {_drop_weights(EVAL_MODEL)}",
    ]
    for name, hf_id, mem in V1_WRITERS:
        start = start_vllm(hf_id, gpu_mem=mem, max_len=4096, extra=f"--served-model-name {name}")
        gen = generate("train-gen", f"configs/action_v1_{name}.json", f"{V1_RAW}/raw1_{name}")
        steps += [
            f"({start}) && ({gen}) || echo 'writer {name} failed' >> artifacts/failed_writers.txt",
            f"{STOP_VLLM}; {_drop_weights(hf_id)}",
        ]
    steps += [
        start_vllm(TRAIN_MODEL, gpu_mem=0.92, max_len=4096, extra="--served-model-name qwen"),
        generate("train-gen", "configs/action_v1_qwen.json", f"{V1_RAW}/raw1_qwen"),
    ]
    for name in [n for n, _, _ in V1_WRITERS] + ["qwen"]:
        out = f"{V1_RAW}/raw1_{name}"
        verify = generate("train-verify", f"configs/action_v1_{name}.json", out)
        steps.append(f"if [ -s {out}/train_gen.jsonl ]; then {verify}; fi")
    steps += [
        generate("eval-verify", "configs/eval_v3.json", f"{V1_RAW}/raw1_eval"),
        generate("eval-verify", "configs/stackchan_v1_paraphrase.json", f"{V1_RAW}/raw1_paraphrase"),
        generate("reverify", "configs/action_v1_qwen.json", f"{V1_RAW}/reverify1")
        + " --input " + " ".join([*V1_REVERIFY_INPUTS, STACKCHAN_SOURCES]),
    ]
    return steps


GEN_ACTION_V1 = JobSpec(
    name="gen_action_v1",
    description="Data v1.0: eval v3 + Stack-chan paraphrases (llm-jp), 5 writers, Qwen3 verifies and re-parses v0.5.1 and the older eval sets under schema v1",
    query=f"gpu_ram>=79 {BASE_QUERY}".replace("disk_space>=120", "disk_space>=200"),
    image=VLLM_IMAGE,
    disk_gb=200,
    max_hours=6.0,
    steps=_v1_steps(),
    uploads=[*V1_REVERIFY_INPUTS, STACKCHAN_SOURCES],
)
```

`reverify` の phase は `sources.jsonl` の行（`text` を持ち `prompt` を持たない）も読めるようにする。Task 9 の `phase_reverify` の `case["prompt"]` を `case.get("prompt", case.get("text"))`、`case["expected"]` を `case.get("expected", [])`、`case["category"]` を `case.get("category", "unknown")` にする（`tests/test_data_generate.py` に `sources.jsonl` 形式の1行の test を足す）。

- [ ] **Step 3: job の定義を確かめる（実行はしない）**

Run: `uv run python -c "from jtalm.infra.jobs import JOBS; j = JOBS['gen_action_v1']; print(len(j.steps), j.max_hours); print(*j.steps, sep='\n')" | head -40`
Expected: steps が表示され、config と出力 dir の名前が Task 11 の `build_v1` と合っている。

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add configs/action_v1_*.json configs/eval_v3.json configs/stackchan_v1_paraphrase.json src/jtalm/infra/jobs.py src/jtalm/data/generate.py tests/test_data_generate.py
git commit -m "jobs: gen_action_v1 (eval v3, Stack-chan paraphrases, five writers, Qwen3 verify and reverify)"
```

- [ ] **Step 5: 【利用者の確認】vast.ai で job を実行する**

利用者に次を示して、実行の許可と1時間あたりの上限額をもらう: job 名、GPU（80GB 以上）、最大 6 時間、過去の実績（データ生成は 1 時間あたり $0.86〜1.22、v0.5 は 1.2 時間）、見込み（4〜6 時間で $4〜8）。

許可が出たら実行する（`--approve-dph` は利用者が答えた上限）。

```bash
uv run python -m jtalm.infra.job gen_action_v1 --approve-dph <利用者の上限>
```

Expected: 終了時に instance が破棄され、`runs/vast/gen_action_v1/` に run.json、artifacts が `artifacts/gen_action_v1/`（または run.json に書かれた場所）に下りてくる。`artifacts/failed_writers.txt` があれば、失敗した書き手を利用者に報告し、その書き手だけの再実行（v0.5.1b と同じ形）を相談する。

- [ ] **Step 6: 組み立てる**

```bash
uv run python -m jtalm.data.stackchan_eval --raw artifacts/gen_action_v1
uv run python -m jtalm.data.build_v1 --raw artifacts/gen_action_v1
```

Expected: `datasets/action/v1.0/{train,val}.jsonl`、`eval_v3/eval.jsonl`、`relabel_v1/*.jsonl` と `changes.md`、`stackchan_v1/eval.jsonl` と `review.md` ができる。manifest の数（引き継ぎ、付け直し、落とした数、新しい文）を確かめる。

- [ ] **Step 7: 【利用者の確認】正解を確認してもらう**

`datasets/action/stackchan_v1/review.md`（全件）と `datasets/action/relabel_v1/changes.md`（v1 で正解が変わった評価の文）を利用者に見せる。直す正解は、利用者の指示どおりに `stackchan_v1/overrides.jsonl`（`{"id": ..., "expected": [...]}`）に書き、Step 6 の `stackchan_eval` をもう一度実行する。`relabel_v1` の変更で認められないものは、同じ形の `relabel_v1/overrides.jsonl` に書き、`build_v1.py` の評価セットの付け直しで読む（このときに `build_v1.py` に overrides の読み込みを足し、test を1つ足す）。

- [ ] **Step 8: tokenizer v1 を作る**

`tokenizer.py` の `train_text` は `data_dir` の train / val を読むのでそのまま使える。出力の名前を `action_v1_sp{v}` にするため、`main` の `args.out / f"action_v0_sp{v}"` を `args.out / f"{args.name}_sp{v}"` にし、`--name`（既定 `action_v1`）を足す。

```bash
uv run --group train python -m jtalm.model.tokenizer --data datasets/action/v1.0 --vocab 2048 --name action_v1 --record datasets/manifests/tokenizer_action_v1.json
```

Expected: `tokenizer/out/action_v1_sp2048.model` ができ、report の `target_roundtrip_ok` が true、`target_tokens_max` が 19 以下（18 + 余裕）。v0 の report と比べて `val_prompts.byte_fallback_rate` が大きく増えていないことを確かめる。

- [ ] **Step 9: manifest を commit する**

stackchan の manifest は `sources.jsonl` の sha256、行数、出典ごとの件数、ライセンスの一覧を書いた JSON にする（`stackchan_eval.py` の `main` に、書き出しを足してもよい）。

```bash
git add datasets/manifests/action_v1.0.json datasets/manifests/action_stackchan_v1.json datasets/manifests/tokenizer_action_v1.json src/jtalm/model/tokenizer.py src/jtalm/data/stackchan_eval.py
git commit -m "Data v1.0, eval v3, Stack-chan eval set v1 (reviewed) and tokenizer action_v1_sp2048: manifests"
```

---

### Task 13: 学習（5 seed）と評価

**Files:**
- Modify: `src/jtalm/infra/jobs.py`
- Modify: `src/jtalm/model/eval_suite.py`
- Create（追跡する）: `results/v1_action/`（run.json、suite、comparison）

**Interfaces:**
- Consumes: `TOKENIZER_V1`、`ACTION_DATA_V1`（Task 12）
- Produces: `jobs.TRAIN_ACTION_V1`（job 名 `train_action_v1`）、`eval_suite` の既定の評価セット（v1 の正解）と、数値の文だけの gate 止まり率

- [ ] **Step 1: `eval_suite` を v1 の評価セットにする**

`DEFAULT_SETS` を次にし、`EV2_DIR` の slice は `datasets/action/relabel_v1/eval_v2_<slice>.jsonl` を読むようにする。`--val` の既定値を `datasets/action/v1.0/val.jsonl` にする。

```python
DEFAULT_SETS = {
    "Stack-chan v1": "datasets/action/stackchan_v1/eval.jsonl",
    "eval v3 (LLM)": "datasets/action/eval_v3/eval.jsonl",
    "v0 eval (LLM)": "datasets/action/relabel_v1/v0_eval.jsonl",
    "human v1": "datasets/action/relabel_v1/human_v1.jsonl",
}
```

`row(report)` に、数値を含む正解の文（正解の call のどれかが `degrees` / `level` / `by` を持つ）のうち、gate で `[]` になった割合 `numeric_gated_rate` を足す。gate 前の出力を持つのは `predict` の行なので、`run_sets` の中で、正解に数値がある case のうち「gate なしの出力は `[]` でなく、gate ありの出力が `[]`」の数を数える（`predict(..., gate=None)` の結果を1回だけ追加で取る）。Stack-chan のセットでは、さらに `source` の種類（verbatim / user / paraphrase）と、look / turn 別の完全一致率を出す。

この変更の test を `tests/test_eval_suite.py`（なければ作る）に1つ足す: 偽の予測（gate なしで `look right 45`、gate ありで `[]`）から `numeric_gated_rate == 1.0` になること。

- [ ] **Step 2: 学習の job を足す**

```python
TOKENIZER_V1 = "tokenizer/out/action_v1_sp2048.model"
ACTION_DATA_V1 = "datasets/action/v1.0"
V1_RUNS = [(f"3m-s{i}", "3m", f"--lr 1e-3 --epochs 12 --seed {i}") for i in range(5)]
TRAIN_ACTION_V1 = JobSpec(
    name="train_action_v1",
    description="Train 3M x5 seeds on data v1.0 (schema v1) in parallel",
    query=f"gpu_ram>=24 compute_cap>=800 compute_cap<=900 {BASE_QUERY}",
    image=VLLM_IMAGE,
    disk_gb=80,
    max_hours=4.0,
    steps=train_action_steps(V1_RUNS, "v1", ACTION_DATA_V1, parallel=True,
                             tokenizer=TOKENIZER_V1, cases=f"{ACTION_DATA_V1}/val.jsonl"),
    uploads=[f"{ACTION_DATA_V1}/train.jsonl", f"{ACTION_DATA_V1}/val.jsonl", TOKENIZER_V1],
)
```

`train_action_steps` に `tokenizer: str = TOKENIZER` と `cases: str = f"{ACTION_DATA}/eval.jsonl"` の引数を足し、`TRAIN` の文字列と最後の evaluate の `--tokenizer` / `--cases` に使う（既存の job の結果は変わらない）。v1 の job の中では評価セットを使わず、validation だけを見る（評価は手元で行う。評価セットを vast.ai に上げないため）。

- [ ] **Step 3: 【利用者の確認】vast.ai で学習する**

見込み（v0.5.1 の実績: 3M を2つ並列で 12 epoch が 731 秒、RTX 3090 で 1 時間あたり $0.15〜0.27。データが約 1.5 倍になり5つ並列なので約 1 時間、$0.3 前後）を示し、許可と上限額をもらう。

```bash
uv run python -m jtalm.infra.job train_action_v1 --approve-dph <利用者の上限>
```

Expected: `artifacts/v1/3m-s{0..4}/best.pt` が下りてくる。

- [ ] **Step 4: 量子化と評価（手元）**

```bash
uv run --group train python -m jtalm.model.quantize --ckpt artifacts/v1/3m-s*/best.pt --bits 4 --group 64
for s in 0 1 2 3 4; do
  uv run --group train python -m jtalm.model.eval_suite --ckpt artifacts/v1/3m-s$s/best_q4_g64.pt \
    --tokenizer tokenizer/out/action_v1_sp2048.model --out results/v1_action/suite_3m-s$s
done
```

（`quantize` の出力の名前は既存のとおり。違えば合わせる。）

Expected: seed ごとに `suite.md` / `suite.json` ができる。

- [ ] **Step 5: 完了の条件と比べる**

seed 0〜4 の平均 ± 標準偏差を、既存の `jtalm.eval.bootstrap`（v0.5.1 の error bar と同じ方法）で出し、`results/v1_action/comparison.md` に spec 2 章の条件ごとに表で書く。

1. 利用者の4文がすべて期待どおり（spec 4.4 の出力）か
2. Stack-chan v1 の完全一致率 ≥ 90%、紛らわしい `[]` の文での誤動作 0 件
3. human v1 の陰性での誤動作 ≤ 0.5%
4. human v1 の陽性の正解率が 85.2 ± 6.4% より下がらない
5. （実機と PyTorch の一致は Task 14 と firmware の計画の F4）
6. （応答時間は firmware の計画の F4）

さらに Review Focus の 1、2、4、5 の数（表記ごとの正解率、`numeric_gated_rate`、範囲外の文、look / turn 別の正解率）を書く。

- [ ] **Step 6: 【利用者の確認】結果を報告し、次を決める**

条件を満たしていれば、公開するモデル（v0 と同じく seed 0。違う seed にする場合は理由を書く）を利用者と決める。満たしていなければ、足りない部分（どの評価セットのどの言い方か）と原因の見立てを示し、データの追加か 5M との比較かを利用者と決める（spec 8 章）。`numeric_gated_rate` が高い場合は、gate の計算から数字の token を除く案を validation だけで比べ、結果を示して決める。

- [ ] **Step 7: Commit**

```bash
git add src/jtalm/infra/jobs.py src/jtalm/model/eval_suite.py tests/test_eval_suite.py results/v1_action
git commit -m "v1 results: 3M x5 seeds on data v1.0 (INT4 + grammar + gate) on the Stack-chan set, eval v3 and the relabeled older sets"
```

---

### Task 14: C runtime と Web の一致を確かめる

**Files:**
- Create（追跡する）: `results/v1_action/parity/`
- Modify: `runtime/web/jtalm.js`（再 build）

- [ ] **Step 1: C runtime と PyTorch の一致（全評価セット）**

```bash
uv run --group train python -m jtalm.model.parity --ckpt artifacts/v1/3m-s0/best.pt \
  --tokenizer tokenizer/out/action_v1_sp2048.model \
  --cases datasets/action/stackchan_v1/eval.jsonl \
  --out runs/local/v1/parity --docker espressif/idf:v5.5.5 --build --bits 4
```

`--cases` を eval v3、relabel_v1 の各ファイル、v1.0 の val にも変えて実行する（`--cases` が複数を受けるなら一度に渡す）。`-DJTLM_ACC=float` の build（実機と同じ）でも実行する（`--jtalm runtime/host/build/accf/jtalm`、`--build` の CFLAGS は既存の README のとおり）。

Expected: INT4 の grammar ありの出力が、すべての case で PyTorch と一致する（v0 と同じく、一致しない case があれば、競った2つの token の確率を見て原因を書く）。結果の要約を `results/v1_action/parity/README.md` に書く。

- [ ] **Step 2: Web の runtime を作り直し、一致を確かめる**

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/src" -w /src emscripten/emsdk:3.1.62 sh runtime/web/build.sh
node runtime/web/parity.cjs <INT4 の .jtlm> <host の出力の JSONL>
```

（`parity.cjs` の引数は `runtime/web/README.md` のとおりに渡す。）

Expected: Web の出力と `min_prob` が host（`-DJTLM_ACC=float`）とすべて一致する。

- [ ] **Step 3: Commit**

```bash
git add runtime/web/jtalm.js results/v1_action/parity
git commit -m "v1 parity: C runtime (double and float accumulation) and WebAssembly equal PyTorch INT4 on every v1 evaluation case"
```

---

### Task 15: 文書を更新し、公開する

**Files:**
- Modify: `README.md`、`README.en.md`、`docs/architecture.md`、`docs/data.md`、`docs/evaluation.md`、`docs/training.md`、`docs/roadmap.md`、`src/jtalm/model/model_card_action.md`
- Modify: `docs/superpowers/specs/2026-10-02-action-schema-v1-design.md`（5.1 の表の `rule_baseline.py` と `classifier.py` の行を「変更なし（v0 の出力は v1 でも正しいので、基準としてそのまま使う）」に直す）
- Create（追跡しない）: `runs/release/action_3m/`（作り直し）

- [ ] **Step 1: 文書を v1 にする**

各文書で、schema v0 の説明（3つの動作、count 1〜3、「LM は角度を出しません」など）を v1 に書き換える。数値は `results/v1_action/comparison.md` から写す（書き写した数と表の数が一致することを確かめる）。`docs/data.md` に v1.0 の作り方（引き継ぎ、付け直しの規則、新しい spec、書き手、検証、件数）、`docs/evaluation.md` に Stack-chan v1 と eval v3 の説明と結果を足す。firmware 側の文書（`docs/hardware.md`、`firmware/README.md`）は firmware の計画で直す。

- [ ] **Step 2: 配布物を作る**

```bash
uv run --group train python -m jtalm.model.release --ckpt artifacts/v1/3m-s0/best.pt \
  --suite results/v1_action/suite_3m-s0 --gate <Task 13 で選んだ閾値> --out runs/release/action_3m
```

（firmware の image は firmware の計画の F4 で作り、`runs/release/action_3m/firmware/` に置く。）

Expected: `config.json` の `"schema"` が `action_schema_v1.json`、`inference.py` が v1、`SHA256SUMS` が更新される。

- [ ] **Step 3: 配布物の `inference.py` で4文を確かめる**

```bash
printf '%s\n' "LEDライトの色を青にして" "音声の音量を50にして" "頭を90度上に向けて" "顔を右に45度向いて" | uv run python runs/release/action_3m/inference.py
```

Expected: spec 4.4 の4つの出力（`set_led blue`、`set_volume 50`、`look up 90`、`look right 45`）。

- [ ] **Step 4: 【利用者の確認】公開する**

モデルカード、配布物の一覧、主な数値を利用者に見せ、公開の許可をもらう。許可が出たら、同じ repo `ayousanz/JapaneseTinyAgentLM-Action-3M` に上書きで upload する（`jtalm.infra.hf` の既存の手順。Discussions / PR が無効のままであることを確かめる）。データ v1.0 の公開（`japanese-data-analyze`）も、データセットカードを見せて別に許可をもらう。Web デモの Space は、`jtalm.js` と `index.html` を更新する。

- [ ] **Step 5: Commit**

```bash
git add README.md README.en.md docs src/jtalm/model/model_card_action.md
git commit -m "Docs and model card for Action schema v1"
```

---

## 自己点検の記録

- spec の各項目と task の対応: 2 章の条件 1〜4 は Task 13、5 は Task 14 と firmware の F4、6 は firmware の F4。4 章は Task 1〜3、6。5.1 は Task 1〜7（`rule_baseline.py` と `classifier.py` は変更なしにし、Task 15 で spec を直す）。5.2 は Task 8、9、11、12。5.3 は Task 10〜12。5.4 は Task 13。5.5 は Task 15。7 章の L1〜L6 は Task 1〜15 に対応する（F1〜F4 は firmware の計画）。
- 型と名前: `TOOLS`、`Arg`、`Tool`（Task 1）→ `all_call_pieces`、`JSON_PIECES`、`ENUM_VALUES`（Task 2）→ `ActionGrammar`（Task 3）→ C の grammar（Task 6）と `hf_inference.Grammar`（Task 7）。`plan_v1`、`Limits`、`DEFAULT_LIMITS` は firmware の計画と同じ名前と形。`relabel`（Task 11）は `uses_v1_only`（Task 1）を使う。
- Review Focus の5項目は、Task 8（spec）、Task 10（実例セット）、Task 13（集計と条件）に入れた。
