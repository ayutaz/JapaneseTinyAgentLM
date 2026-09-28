# 開発ロードマップと評価計画

最終更新: 2026-09-29

## 1. 方針

最初に小さな Action Model を成立させ、次に Chat、ESP32 Runtime、Ralomi 統合、Unified 化へ進みます。各 phase には明示的な exit gate を置き、学習が完了しただけでは次へ進みません。

## 2. Phase 0: 制約の実測と仕様固定

### 作業

- CoreS3 と対象 Stack-chan hardware revision を固定。
- `stackchan-idf` の対象 commit と build options を固定。
- Firmware、partition、sanoTTS-jp、assets の Flash 使用量を実測。
- Idle / display / audio / Wi-Fi / TTS ごとの SRAM・PSRAM peak を実測。
- Action vocabulary、値域、no-op policy を定義。
- Ralomi → LM interface v0 を文書化。
- Dataset provenance と license policy を定義。
- 共通 benchmark harness と結果 JSON schema を作る。

### Exit gate

- Flash map の合計が artifact 実測値で説明できる。
- PSRAM / internal SRAM の phase 別 high-water mark が取得できる。
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

- 単一 action / 複合 action。
- 左右、上下、角度、強度、相対表現。
- 否定、取消、訂正、「もう少し」「さっきと逆」等の context 依存。
- 丁寧語、口語、方言候補、表記ゆれ。
- ひらがな入力 / 漢字仮名交じり入力。
- ASR 誤り simulation。
- 無関係要求、曖昧要求、危険要求の no-op。
- 未知 tool / 未知 slot を含む adversarial input。

### Model axis

- 3M / 5M / 10M。
- INT8 / INT4。
- context 64 / 128 / 256。
- Grammar なし / あり。
- Base から SFT / Action-only scratch training。

### Exit gate 候補

- JSON parse success: 100%（grammar 使用時）。
- Schema validity: 100%（grammar + validator 使用時）。
- Action semantic exact match: 目標値は baseline 後に固定。
- Critical slot（方向、否定、速度、角度）の error budget を別設定。
- OOD / 無関係入力の false action rate が許容値以下。
- Host INT4 が FP reference から許容範囲の精度低下。

絶対目標値は dataset 難易度を見ずに先に決めません。まず random、rule-based parser、小型 classifier / seq2seq を baseline とし、モデルが単純手法を上回ることを要求します。

## 5. Phase 3: Japanese Tiny Chat LM

### 対象

- 10M / 20M を主比較。
- 1〜3 turn の短い会話。
- 応答は短く、TTS しやすい句読点・読み。
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
9. Stack-chan command dispatch。

### 実機評価指標

| 分類 | 指標 |
|---|---|
| 速度 | Prompt tokens/s、decode tok/s、first-token latency、action completion latency |
| Memory | Peak internal SRAM、peak PSRAM、largest free block、fragmentation、stack high-water mark |
| Flash | Firmware、model、Tokenizer、grammar、assets、partition slack |
| 品質 | Host と実機の token match、Action exact match、quantization delta |
| 安定性 | 連続100/1,000 request、watchdog、heap leak、thermal behavior |
| 電力 | Idle / listening / thinking / speaking の電流・energy per request |

### Exit gate

- Host / device greedy token が test vector で一致、または量子化仕様上の差を説明可能。
- 連続実行で leak、reset、buffer overrun がない。
- Memory safety reserve を維持。
- Action の end-to-end latency が UX 要件を満たす。要件値はユーザーテスト後に固定。

## 7. Phase 5: Ralomi / TTS / Stack-chan 統合

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
- **Exact match**: canonicalize 後の action 列完全一致率。
- **Action type accuracy**: look / emotion / speak 等の分類正解率。
- **Slot accuracy / F1**: yaw、pitch、emotion 等。
- **Sequence accuracy**: 複合 action の順序を含む一致。
- **No-op precision / recall**: 実行すべきでない入力を止める能力。
- **Critical error rate**: 逆方向、否定無視、過大値、未知 action 等。
- **Paraphrase consistency**: 同義表現で同じ canonical action を返す率。

### Chat

- Validation loss / bits per byte。
- Human preference と rubric score。
- Relevance、naturalness、brevity、persona consistency。
- Repetition / degeneration / truncation rate。
- Unsupported claim / device-state hallucination rate。
- TTS frontend で読めない文字・記号の出現率。

### Device

- First-token latency、total latency、prompt/decode tok/s。
- Flash bytes、peak PSRAM、peak internal SRAM、largest free block。
- Energy per request、temperature、battery impact。
- Cold boot、model load、prompt prime time。
- 連続 request の crash / watchdog / leak rate。

測定値には必ず board、CPU clock、PSRAM mode、Firmware commit、model hash、prompt/context、生成長、warm/cold 条件を添えます。

## 11. 今後追加調査すべき項目

優先度順:

1. CoreS3 + `stackchan-idf` + sanoTTS-jp の実 Flash/PSRAM map。
2. Ralomi の最新 private specification、artifact、quality gate、license。
3. Needle 2 の artifact format、kernel、grammar の再利用可能性と license。
4. ESP32-S3 SIMD / ESP-DSP / ESP-NN / ESP-DL を使う quantized GEMV の比較。
5. MQA/GQA、KV INT8、sliding window、recompute の速度・メモリ trade-off。
6. 日本語 Action dataset の設計、合成比率、人手検証、権利。
7. ひらがな-only と mixed Japanese の controlled comparison。
8. Rule-based parser、小型 classifier、seq2seq との比較。
9. 既存の日本語 on-device tool-calling model、論文、製品、特許の網羅調査。
10. Grammar compiler の supported subset と code size。
11. Flash mmap、microSD streaming、external storage の latency。
12. OTA / rollback / recovery partition を残したまま成立する構成。
13. Servo safety、child-facing device、privacy、offline data retention の要件。
14. 実ユーザーによる latency と品質の許容水準。
15. GitHub / Hugging Face 名称、商標、license、release packaging。

## 12. 最初の具体的な実験

最初の1サイクルは次に限定します。

1. Action schema v0 を `look` / `emotion` / no-op の3種類に絞る。
2. ひらがなと漢字仮名交じりを対にした小規模 dataset を作る。
3. 3M と5Mを Host で学習。
4. Grammar なし/ありで exact match と no-op を比較。
5. INT8 → INT4 の精度差を測る。
6. 5M INT4 を ESP32-S3 に載せ、Flash、PSRAM、tok/s、latency を測る。
7. 結果を見て 10M Action または 10M Chat のどちらへ進むか決める。

これにより、最も重要な「日本語 Action LM は小型化しても成立するか」を、Full pipeline の複雑さから切り離して検証できます。
