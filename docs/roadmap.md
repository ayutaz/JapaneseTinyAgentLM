# 開発ロードマップと評価計画

最終更新: 2026-09-29

## 1. 方針

**本計画の範囲は LLM（Chat / Action）を作ることです**（2026-09-29 決定）。範囲に含めるのは、学習、量子化、ESP32-S3 上の推論 runtime、Action による servo 制御までです。

TTS（sanoTTS-jp）と ASR（Ralomi）については、調査も同居の検証も本計画では行いません。LM は [`architecture.md`](architecture.md) §9–10 の **LM 用の Flash / PSRAM 予算だけを前提**に開発します。ASR → LM → TTS の統合（Phase 5）は将来の別計画とします。

最初に小さな Action Model を成立させ、次に Chat、ESP32 Runtime、Unified 化へ進みます。各 phase には明示的な exit gate を置き、学習が完了しただけでは次へ進みません。

作業は2つの track に分け、並行して進めます。

- **Track A（PC 上）:** Phase 1〜3 と Host runtime。学習は vast.ai で行う（[`development.md`](development.md)）。
- **Track B（実機上）:** Phase 0 の計測と Phase 4 の ESP32 移植。

Phase 0 の exit gate は、実機の予算に依存する判断（partition、量子化の下限）の前提です。ただし、PC 上の学習と評価の開始は妨げません。具体的なマイルストーンは §12 にまとめます。

## 2. Phase 0: 制約の実測と仕様固定

### 作業

- CoreS3 と対象 Stack-chan hardware revision を固定。→ **完了**。対象は M5 スタックチャン K151（[`hardware.md`](hardware.md)）。
- 実機用 build の基盤を固定する。→ **方針決定**。
  - ESP-IDF は **v5.5.5** に固定する。K151 に対応している公式 `m5stack/StackChan`（v5.5.4）と `stackchan-idf`（v5.5.5 で検証）に合わせるためで、最新の v6.1 は使わない。
  - LM の評価には、LM runtime と servo 制御だけを持つ**自前の最小 firmware** を使う。
  - Servo の driver は、`stackchan-idf`（BSL-1.0）の `scs_servo` か、公式（MIT）の driver を流用する。
- 実機を動かして、yaw の符号（公式規約では正の値が右）と pitch の中立角度を確認する。
- 自前の最小 firmware で、Flash の使用量と、状態ごと（idle / 画面表示 / servo 駆動 / LM 推論）の内部 SRAM・PSRAM の peak を実測し、**LM が使える予算を確定する**。
- Action vocabulary、値域、no-op policy を定義。
- LM の入力仕様（ひらがな入力 / 漢字仮名交じり入力）を文書化する。
- Dataset provenance と license policy を定義。
- 共通 benchmark harness と結果 JSON schema を作る。

### Exit gate

- LM 評価用 firmware の Flash map の合計が、artifact の実測値で説明できる。
- PSRAM / internal SRAM の状態ごとの high-water mark が取得でき、LM の予算が数値で決まっている。
- Action schema v0 と safety validator の仕様がレビュー済み。
- Dataset を「使用可」と判断する根拠が記録されている。

## 3. Phase 1: Tokenizer と Base LM

### 実験

- ひらがな中心 vocab 2k / 4k。
- 一般日本語 vocab 4k / 8k。
- 3M / 5M / 10M / 20M config を同一 code path で生成。
- 小規模 corpus で overfit test、loss curve、resume、determinism を確認。
- Host reference forward と artifact loader を作る。

### 評価

- validation loss / perplexity。ただし Tokenizer 間では token-level perplexity を直接比較しない。
- bits per byte または同一文字列あたり negative log likelihood。
- 文字・モーラあたり token 数。
- P50 / P95 sequence length。
- Training tokens、FLOPs 概算、wall time、checkpoint size。

### Exit gate

- Held-out loss が training leak なしで再現。
- Tokenizer round-trip が UTF-8 corpus で 100%。
- Host inference が training framework の logits / greedy tokens と許容誤差内で一致。

## 4. Phase 2: Japanese Action LM

### Dataset axis

- 単一 action / 複合 action（0〜2個、順序つき）。
- 左右、上下、強度（`slight` / `normal` / `large`）、相対表現。
- 否定、取消、訂正、「もう少し」「さっきと逆」等の context 依存。
- 丁寧語、口語、方言候補、表記ゆれ（全角・半角、句読点、省略）。
- ひらがな入力 / 漢字仮名交じり入力。
- 音声認識の誤りを模した表記ゆれ。
- 無関係要求、曖昧要求、危険要求の no-action。「何もしないで」のような明示的な no-action も含む。
- 未知 tool / 未知 slot を含む adversarial input。
- 少量の英語の命令（評価用）。

**multi-action、否定、no-action** は、TinyLM-Bench で既存の3モデルがすべて失敗したカテゴリです（[`research_notes.md`](research_notes.md) §3.7）。この3つは独立したカテゴリとして、学習でも評価でも厚く扱います。

### Model axis

- 3M / 5M / 10M。
- INT8 / INT4。
- context 64 / 128 / 256。
- Grammar なし / あり。
- Base から SFT / Action-only scratch training。

### Exit gate 候補

| 指標 | 暫定の目標 |
|---|---:|
| JSON parse success（grammar 使用時） | 100% |
| Schema validity（grammar + validator 使用時） | 100% |
| Action の完全一致率 | 90%以上 |
| multi-action の正解率 | 90%以上 |
| 否定の正解率 | 90%以上 |
| No-action の正解率 | 95%以上（最優先） |
| Host INT4 と FP reference の差 | 許容範囲内 |

- 上の目標値は、TinyLM-Bench の検証メモ（94）の提案を**暫定値**として採用したものです。Baseline とデータセットの難易度を見てから見直します。
- Critical slot（方向、否定、量）の error budget は別に設定する。
- OOD / 無関係な入力で誤って動作してしまう率を、許容値以下にする。
- **既存モデルに勝つこと:** TinyLM-Bench の共通評価（16件と、その拡張版）で、Needle 2、FunctionGemma 270M、MimiModel の厳格一致率を上回る。

Baseline は、単純な手法（random、rule-based parser、小型 classifier / seq2seq）と、既存モデル（TinyLM-Bench の上記3モデル）の両方にします。モデルは、単純な手法と既存モデルの両方を上回ることを要求します。

## 5. Phase 3: Japanese Tiny Chat LM

### 対象

- 10M / 20M を主比較。
- 1〜3 turn の短い会話。
- 応答は短く、句読点や記号の使い方が自然。
- 知らない内容を作らない、デバイス能力を誤認させない。

### 評価

- Held-out loss / bits per byte。
- Instruction adherence。
- Relevance、自然さ、一貫性、簡潔さ。
- Repetition rate、文字化け、未完文、無限生成。
- Hallucinated device state / unsupported capability rate。
- Human pairwise preference。
- 生成長別 first-token latency と tok/s。

### Exit gate

- Rule/template baseline より、対象シナリオの human preference で優位。
- 最大生成長で timeout / watchdog reset がない。
- 品質評価者間一致と rubric が記録されている。

## 6. Phase 4: ESP32-S3 Runtime

### 実装順

1. Artifact header / checksum / version validation。
2. Tokenizer exact-match test。
3. Quantized GEMV unit test。
4. 1 layer forward golden test。
5. Full forward golden test。
6. Incremental KV decode test。
7. Grammar mask test。
8. End-to-end Action decode。
9. Stack-chan command dispatch。検証済みの Action を、K151 の SCS0009 servo（UART1、`G6` / `G7`）への命令に変換する。入力は PC から serial で与える固定テキストとする。

### 実機評価指標

| 分類 | 指標 |
|---|---|
| 速度 | Prompt tokens/s、decode tok/s、first-token latency、action completion latency |
| Memory | Peak internal SRAM、peak PSRAM、largest free block、fragmentation、stack high-water mark |
| Flash | Firmware、model、Tokenizer、grammar、assets、partition slack |
| 品質 | Host と実機の token match、Action exact match、quantization delta |
| 安定性 | 連続100/1,000 request、watchdog、heap leak、thermal behavior |
| 電力 | Idle / 推論中 / servo 駆動中の電流・energy per request |

### Exit gate

- Host / device greedy token が test vector で一致、または量子化仕様上の差を説明可能。
- 連続実行で leak、reset、buffer overrun がない。
- Memory safety reserve を維持。
- Action の end-to-end latency が UX 要件を満たす。要件値はユーザーテスト後に固定。

## 7. Phase 5: Ralomi / TTS / Stack-chan 統合（本計画の対象外）

> [!NOTE]
> 2026-09-29 の決定により、この phase は本計画の対象外です。本計画は Phase 4（LM 単体での実機評価と、Action による servo 制御）までを範囲とします。以下は、将来の統合計画の参考として残しています。

### 段階

1. 固定 text → Action → mock driver。
2. PC ASR → text → CoreS3 Action。
3. Ralomi artifact → text → CoreS3 Action。
4. Chat text → sanoTTS-jp。
5. ASR → LM → TTS / Servo / Face の完全 pipeline。

### 時分割検証

- LISTENING 終了時に ASR arena が解放・再利用可能か。
- THINKING 中に microphone ring buffer をどこまで保持するか。
- SPEAKING 中に次の wake word を受けるか、排他するか。
- LCD / Servo task と inference task の priority / core affinity。
- Cancellation、barge-in、timeout、brownout、watchdog。

### End-to-end 指標

- ASR word/mora error ではなく、最終 Action exact match。
- ASR oracle text と実 ASR の差。
- 音声終了から action 開始までの latency。
- 音声終了から発話開始までの latency。
- 方向・否定・数値の critical error rate。
- 連続セッションでの peak memory と電力。

## 8. Phase 6: Unified Model

### 比較

- Separate Chat + Action checkpoint。
- `<chat>` / `<action>` token を持つ Unified checkpoint。
- Shared Base + small adapter/head。
- Action grammar のみ mode-specific。

### 採用条件

- Flash 使用量が明確に減る。
- Chat と Action の各品質が separate baseline から許容範囲以上落ちない。
- Mode leakage が実用上無視できる。
- Runtime complexity と artifact management が悪化しすぎない。

Unified が失敗しても研究成果です。原因を capacity、data balance、optimization、mode conditioning に分解し、Separate を正式構成として維持します。

## 9. Phase 7: OSS / Model 公開

### 公開物

- Source、build 手順、training config。
- Dataset manifest と provenance。
- Tokenizer、model、quantized ESP32 artifact。
- SHA-256 checksum。
- Host / device benchmark raw JSON。
- Model card と limitation。
- Demo は再現可能な commit / board / config を明記。

### Release gate

- License と再配布権の確認。
- Private data、個人情報、credential の除外。
- Git history と artifact の secret scan。
- Hardware safety test。
- Third-party notices。
- Ralomi は独立した公開判断。開発中の private project を依存物として自動公開しない。

## 10. 評価指標の定義

### Action

- **JSON validity**: parse 可能な出力率。
- **Schema validity**: schema に適合する出力率。
- **Exact match**: canonicalize 後の action 列完全一致率。TinyLM-Bench の「厳格一致」と同じ定義にする。
- **カテゴリ別の exact match**: single、multi-action、否定、no-action ごとに集計し、日本語と英語も分ける。
- **Action type accuracy**: look / set_expression / nod の分類正解率。
- **Slot accuracy / F1**: direction、amount、expression、count。
- **Sequence accuracy**: 複合 action の順序を含む一致。
- **No-action precision / recall**: 実行すべきでない入力を止める能力。
- **Confidence gate の効果**: gate による no-action への切り替え率と、誤作動率の変化。
- **Critical error rate**: 逆方向、否定無視、enum 外の値、未知 action 等。
- **Paraphrase consistency**: 同義表現で同じ canonical action を返す率。

### Chat

- Validation loss / bits per byte。
- Human preference と rubric score。
- Relevance、naturalness、brevity、persona consistency。
- Repetition / degeneration / truncation rate。
- Unsupported claim / device-state hallucination rate。
- 不要な記号、絵文字、制御文字の出現率。

### Device

- First-token latency、total latency、prompt/decode tok/s。
- Flash bytes、peak PSRAM、peak internal SRAM、largest free block。
- Energy per request、temperature、battery impact。
- Cold boot、model load、prompt prime time。
- 連続 request の crash / watchdog / leak rate。

測定値には必ず board、CPU clock、PSRAM mode、Firmware commit、model hash、prompt/context、生成長、warm/cold 条件を添えます。

## 11. 今後追加調査すべき項目

優先度順:

1. K151 上で、自前の最小 firmware（LM runtime と servo 制御）の Flash / PSRAM map を測り、LM の予算を確定する。
   - 1a. Yaw の符号と pitch の中立角度を実機で確認する。
2. Needle 2 の artifact format、kernel、grammar の再利用可能性と license。
3. ESP32-S3 SIMD / ESP-DSP / ESP-NN / ESP-DL を使う quantized GEMV の比較。
4. MQA/GQA、KV INT8、sliding window、recompute の速度・メモリ trade-off。
5. 日本語 Action dataset の設計、合成比率、人手検証、権利。
6. ひらがな-only と mixed Japanese の controlled comparison。
7. Rule-based parser、小型 classifier、seq2seq との比較。
8. 既存の日本語 on-device tool-calling model、論文、製品、特許の網羅調査。
9. Grammar compiler の supported subset と code size。
10. Flash mmap、microSD streaming、external storage の latency。
11. OTA / rollback / recovery partition を残したまま成立する構成。
12. Servo safety、child-facing device、privacy、offline data retention の要件。
13. 実ユーザーによる latency と品質の許容水準。
14. GitHub / Hugging Face 名称、商標、license、release packaging。

TTS（sanoTTS-jp）と ASR（Ralomi）に関する調査は、本計画の範囲外として外しました（2026-09-29）。

## 12. 最初の具体的な実験

最初の1サイクルは次に限定します。

1. Action schema v0 を `look` / `set_expression` / `nod` / no-action に絞る。形式は TinyLM-Bench と同じにし、1回の出力は 0〜2個とする（[`architecture.md`](architecture.md) §7）。
2. ひらがなと漢字仮名交じりを対にした dataset を作る。multi-action、否定、no-action を独立したカテゴリにする。
3. 3M と5Mを学習する（vast.ai 上）。
4. Grammar なし/ありと confidence gate なし/ありで、カテゴリ別の exact match と no-action を比較する。
5. INT8 → INT4 の精度差を測る。
6. TinyLM-Bench の共通評価で、既存モデル（Needle 2、FunctionGemma 270M、MimiModel）と比べる。
7. 5M INT4 を ESP32-S3 に載せ、Flash、PSRAM、tok/s、latency を測る。
8. 結果を見て 10M Action または 10M Chat のどちらへ進むか決める。

これにより、最も重要な「日本語 Action LM は小型化しても成立するか」を、Full pipeline の複雑さから切り離して検証できます。

最初の1周は、**Action 専用のスクラッチ学習**で行います。日本語の事前学習 corpus を選ぶと、そのライセンスがモデル重みのライセンスに直結するためです。corpus の選定を blocker にせず、Base の事前学習と SFT の比較（Phase 2 の Model axis）は corpus のライセンスが決まってから行います。

### 進捗（2026-09-29 時点）

| 項目 | 状態 |
|---|---|
| Private repository の作成、LICENSE（Apache-2.0）、`.gitignore` | 完了 |
| 設計文書（`docs/`） | 完了（本更新を含む） |
| B0 実機の初回調査 | 完了 |
| M1 以降 | 未着手。次は M1 と M2 |

### Track A: PC 上の実装マイルストーン

| # | マイルストーン | 成果物 | 完了条件 |
|---|---|---|---|
| M1 | リポジトリ基盤 | `pyproject.toml` / `uv.lock`（`uv add` のみ）、pytest、ruff、`.env.example`。Python は PyTorch 2.14 系と SentencePiece の wheel がそろう版に固定する（第一候補は 3.13） | `uv sync --locked` と test がローカルで通る |
| M2 | Action schema v0 と評価の土台 | `grammar/action.schema.json`（TinyLM-Bench と同じ形式、0〜2個）、validator、正規化処理、評価指標（カテゴリ別の exact match、slot、no-action の precision / recall、critical error）、カテゴリから角度への変換表 | TinyLM-Bench の16件の期待値が、validator と評価器を通る。K151 の座標規約（[`architecture.md`](architecture.md) §7）に沿った unit test が通る |
| M3 | Dataset v0 と baseline | 合成データ（ひらがな版と漢字仮名交じり版の対、言い換え、multi-action、否定、no-action、少量の英語）、**手書きの test set**、ルールベース parser、既存モデルの結果（TinyLM-Bench） | 評価セットが1,000件以上で、重要カテゴリ（multi-action、否定、no-action）が各100件以上ある。テンプレート単位で分割し、baseline の数値が出ている |
| M3.5 | vast.ai 実行基盤 | `infra/vast/`（GPU の検索 → instance 作成 → `git archive` で転送 → `uv sync --locked` → 学習 → 回収 → 削除）。CLI は `uv add --dev vastai`（1.8 系）で lock する | 小さな学習で、一連の流れと instance の削除を確認し、費用を記録している |
| M4 | Tokenizer と 3M / 5M の学習 | SentencePiece（2k / 4k / 8k を比較）、decoder-only Transformer、学習 script | ローカルの CPU smoke test を通してから、vast.ai 上で学習を完走する |
| M5 | Grammar 制約、confidence gate、量子化 | grammar-constrained decoding（Python）、confidence gate、INT8 / INT4 の fake quant、比較表 | 上の手順 4〜6 の比較結果が揃っている |
| M6 | Host C reference runtime | portable C の推論コード、golden vector | PyTorch の出力と、token が一致している |

M3 の test set を手書きにするのは、テンプレートで生成したデータで評価すると、テンプレートを暗記しているだけで高得点になるためです。

### Track B: 実機上のマイルストーン

| # | マイルストーン | 内容 |
|---|---|---|
| B0 | 実機の初回調査 | **完了**（2026-09-29）。対象機の特定、SoC / Flash / PSRAM、Flash 全体のバックアップ（[`hardware.md`](hardware.md)） |
| B1 | ESP-IDF の build 環境 | ESP-IDF **v5.5.5** の公式 Docker image（`espressif/idf:v5.5.5`）で build する。ローカルへの導入は不要。書き込みは Windows から `esptool` で行う |
| B2 | Servo の座標の確認 | K151 に対応した `stackchan-idf`（v5.5.5 で検証済み）を build して書き込み、yaw の符号と pitch の中立角度を確認する |
| B3 | LM 評価用の最小 firmware | LM runtime の枠組み、servo 制御、計測用の telemetry だけを持つ自前の firmware を作る。Flash map と状態ごとの SRAM / PSRAM の peak を測り、LM の予算を確定する（Phase 0 の exit gate） |
| B4 | ESP32 への移植 | M6 の C runtime を B3 の firmware に載せ、5M INT4 の tok/s、latency、PSRAM の peak を測る。Action を servo の命令に変換して実際に動かす |

B2 以降は、実機の firmware を書き込む前に必ずバックアップを取ります（[`development.md`](development.md) §5）。

### 判断ポイント

M5 と B4 の結果が揃った時点で、次のどちらへ進むかを決めます。

- **5M Action が baseline に勝ち、実機にも収まった場合:** 10M Chat（Base の事前学習を含む）へ進む。
- **精度が足りない場合:** 10M Action、またはデータと Tokenizer の見直しへ進む。
