# 開発ロードマップと評価計画

最終更新: 2026-09-29

## 1. 方針

**本計画の範囲は LLM（Chat / Action）を作ることです**（2026-09-29 決定）。範囲に含めるのは、学習、量子化、ESP32-S3 上の推論 runtime、Action による servo 制御までです。

TTS（sanoTTS-jp）と ASR（Ralomi）については、調査も同居の検証も本計画では行いません。LM は [`architecture.md`](architecture.md) §9–10 の **LM 用の Flash / PSRAM 予算だけを前提**に開発します。ASR → LM → TTS の統合（Phase 5）は将来の別計画とします。

最初に小さな Action Model を成立させ、ESP32 Runtime で K151 の実機に載せて完成させます。そのあとで Chat、Unified 化へ進みます。各 phase には明示的な exit gate を置き、学習が完了しただけでは次へ進みません。

作業は2つの track に分け、並行して進めます。

- **Track A（PC 上）:** Phase 1〜2 と Host runtime。Phase 3（Chat）は、Action LM の完成後に取り組む。学習と合成データの生成は vast.ai で行う（[`development.md`](development.md)）。
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
- Action vocabulary、値域、no-action policy を定義。→ **完了**（M2。Action schema v0 と `[]` の扱いは `src/jtalm/action/`、評価は `jtalm.eval`。confidence gate は M5 で実装する。[`architecture.md`](architecture.md) §7–8）。
- LM の入力仕様を文書化する。→ **決定済み**（テキストのみ、UTF-8、漢字仮名交じり文が主。[`architecture.md`](architecture.md) §12）。
- Dataset provenance と license policy を定義。→ **完了**（[`data.md`](data.md)、M3 の manifest `datasets/manifests/action_v0.json`）。
- 共通 benchmark harness と結果 JSON schema を作る。→ Action の評価器は M2 で実装済み（`jtalm.eval`）。実機の harness と結果の JSON schema は、B2.5 / B3 で作る。

### Exit gate

- LM 評価用 firmware の Flash map の合計が、artifact の実測値で説明できる。
- PSRAM / internal SRAM の状態ごとの high-water mark が取得でき、LM の予算が数値で決まっている。
- Action schema v0 と safety validator の仕様がレビュー済み。
- Dataset を「使用可」と判断する根拠が記録されている。

## 3. Phase 1: Tokenizer と Base LM

### 実験

- Action 用 vocab 2k / 4k / 8k（M4 で固定）。
- Chat 用 vocab 4k / 8k / 12k / 16k（Chat の段階で固定）。
- 3M / 5M / 10M / 20M config を同一 code path で生成（20M は PC だけの上限参照）。
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
- 漢字仮名交じり入力を主とする（入力はテキストのみ）。ひらがなだけの入力は、頑健性の確認用に一部だけ入れる。
- 入力ミスや変換ミスを模した表記ゆれ。
- 無関係要求、曖昧要求、危険要求の no-action。「何もしないで」のような明示的な no-action も含む。
- 未知 tool / 未知 slot を含む adversarial input。
- 少量の英語の命令（評価用）。
- **対比ペア:** 「右を向いて」と「右を向かないで」、「笑って」と「笑わないで」のように、否定の有無だけが違う組を入れる。
- **重複の禁止:** 同じ action を繰り返さない例を入れる。
- **Tool の範囲外の要求:** 「部屋の電気を消して」のような要求に no-action を返す例を入れる。

**multi-action、否定、no-action** は、TinyLM-Bench で既存の3モデルがすべて失敗したカテゴリです（[`research_notes.md`](research_notes.md) §3.7）。この3つは独立したカテゴリとして、学習でも評価でも厚く扱います。

### データの規模と配分

| 項目 | 目標 |
|---|---|
| 最初の1周の学習データ | 高品質な日本語の合成データ 2,000〜10,000件 |
| 否定の割合 | 20%以上 |
| No-action の割合 | 20%以上（雑談、質問、状態の説明、曖昧な命令、tool の範囲外の要求を含む） |
| 評価セット | 1,000件以上。重要カテゴリ（multi-action、否定、no-action）は各100件以上 |
| 分割 | 生成元（モデルと prompt）で学習データと評価セットを分け、重複と重なりを除く（M3 で実施。テンプレート単位の分割は行っていない。label-first の生成にしたため） |

TinyLM-Bench の16件は、開発中の smoke test として使います。モデルの選定には使いません。

### Model axis

- 3M / 5M / 10M（実機に載せる候補）。
- 20M（必要なら 50M）: 実機には載せない上限参照（学習は vast.ai、評価は PC 上の host だけで行う）。3M / 5M の精度が低いとき、原因が capacity なのか、data や tokenizer なのかを切り分ける（[`architecture.md`](architecture.md) §3）。
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
| No-action の正解率（recall） | 95%以上（最優先） |
| No-action の precision（動作の依頼を誤って `[]` にしない） | 0.90 以上（M4 の後に追加） |
| Host INT4 と FP reference の差 | 許容範囲内 |

- 上の目標値は、TinyLM-Bench の検証メモ（94）の提案を**暫定値**として採用したものです。M4 の最初の評価（2026-09-29、§12「M4 の結果」）の後に見直し、値は据え置きました。no-action には **precision 0.90 以上**の目標を加えます（ルールベースは 0.80、M4 の 3M は 0.86）。英語の命令は学習データに入れていないので、参考値として扱います。
- Critical slot（方向、否定、量）の error budget は別に設定する。
- OOD / 無関係な入力で誤って動作してしまう率を、許容値以下にする。
- **既存モデルに勝つこと:** TinyLM-Bench の共通評価（16件）で、Needle 2、FunctionGemma 270M、MimiModel の厳格一致率を上回る。既存モデルは 16件分の出力しか手元にないため、1,189件の評価セットでの比較は、M5 で TinyLM-Bench の host 環境で流せるかを判断する。
- **ルールベースの baseline に勝つこと:** M3 の評価セット（1,189件）で、ルールベースの baseline（完全一致 76.4%）を、全体とカテゴリ別（特に single 60.9%、multi_action 46.9%）の両方で上回る。

Baseline は、単純な手法（random、rule-based parser、小型 classifier / seq2seq）と、既存モデル（TinyLM-Bench の上記3モデル）の両方にします。モデルは、単純な手法と既存モデルの両方を上回ることを要求します。

## 5. Phase 3: Japanese Tiny Chat LM

### 対象

- 実機の候補は 10M。20M は PC での品質比較（2-bit 量子化で実機に載るかは、kernel と品質が成立した場合のみ検討する）。
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

### Baseline

- Rule / template による応答。
- 日本語の生成の baseline として、LLM-jp-3-150M-instruct3（PC のみ）。日本語は流暢だが、約 1.25GB の RSS を使い、指示への追従も不安定だった（[`research_notes.md`](research_notes.md) §3.7）。
- 英語の小型 Chat の参考として、TinyTalk 2 / cardputer-ai。日本語の入力には、即座に EOS を返すだけだった。

### Exit gate

- Rule/template baseline より、対象シナリオの human preference で優位。
- 日本語の対象シナリオで、LLM-jp-3-150M-instruct3 との差を定量的に示している（10M なら約 1/15、20M でも約 1/7.5 の規模であることを考慮する）。
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
| 起動 | Cold boot、warm start、model load の時間 |
| 安定性 | 連続10 / 100 / 1,000 request、watchdog、heap leak |
| 温度 | Chip 温度、clock の低下（thermal throttling） |
| 周辺機能 | 画面と servo を有効にしたときの、memory と速度の差分 |
| 電力 | Idle / 推論中 / servo 駆動中の電流・energy per request |

どの計測にも、firmware の commit と build flags、Flash の partition、model hash、同じ評価入力、serial log の生データを添えます。Windows host の RSS は、実機の memory の代わりにはなりません。

### Exit gate

- Host / device greedy token が test vector で一致、または量子化仕様上の差を説明可能。
- 連続実行で leak、reset、buffer overrun がない。
- Memory safety reserve を維持。
- Action の end-to-end latency が UX 要件を満たす。要件値はユーザーテスト後に固定。

## 7. Phase 5: Ralomi / TTS / Stack-chan 統合（本計画の対象外）

> [!NOTE]
> 2026-09-29 の決定により、この phase は本計画の対象外です。本計画は Phase 0〜4、6、7 を範囲とし、この Phase 5 だけを対象外とします。LM は、単体での実機評価と Action による servo 制御までを行います。以下は、将来の統合計画の参考として残しています。

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

モデルは Hugging Face で、オープンモデルとして公開します。利用者として想定しているのは開発者です（[`README.md`](README.md) §1）。

最初に公開するのは、Action LM が完了条件（§4）と実機の基準（Phase 4）を満たした時点です。Chat LM は、完成してから追加で公開します。

### 公開物

| 公開先 | 内容 | ライセンス |
|---|---|---|
| Hugging Face（model、user `ayousanz`） | FP の checkpoint、ESP32 向けの量子化 artifact、tokenizer、SHA-256 checksum。公開の前にユーザーの確認を取る | CC BY-SA 4.0 |
| Hugging Face | モデルカード（用途、Action schema、角度への変換規約、評価結果、既知の限界、禁止用途） | CC BY-SA 4.0 |
| Hugging Face（dataset） | 合成データセットとデータセットカード。organization `japanese-data-analyze` に **public、manual gate** で公開する。モデルより先に、M3 の時点で公開する（[`data.md`](data.md) §6） | CC BY-SA 4.0 |
| GitHub | 学習と評価の code、training config、ESP32 runtime、build の手順 | Apache-2.0 |
| GitHub | Dataset manifest と provenance、host と実機の benchmark の生の JSON | Apache-2.0（データ本体は、それぞれのライセンスに従う） |

- GitHub の repository（`ayutaz/JapaneseTinyAgentLM`）は現在 private です。公開する時期は、この Phase で判断します。
- デモには、再現できる commit、board、config を明記する。
- ESP-IDF の component としての runtime と、tool を追加するための fine-tuning の手順を公開するかは、モデルが完成してから判断する（2026-09-29 決定）。

### Release gate

- 学習データがすべて CC BY-SA 4.0 と両立すること。出典とライセンスが manifest に記録されていること（[`development.md`](development.md) §6）。
- 学習データの中身（文章とラベル）に、Claude や ChatGPT などの規約で制限された出力が含まれていないこと（[`data.md`](data.md) §1）。
- Private data、個人情報、credential の除外。
- Git history と artifact の secret scan。
- Hardware safety test（servo の可動域、no-action、confidence gate）。
- Third-party notices。
- モデルカードに、CC BY-SA 4.0 の表示方法と継承の条件を明記する。

## 10. 評価指標の定義

### Action

- **JSON validity**: parse 可能な出力率。
- **Schema validity**: schema に適合する出力率。
- **Exact match**: canonicalize 後の action 列完全一致率。TinyLM-Bench の「厳格一致」と同じ定義にする。
- **カテゴリ別の exact match**: single、multi-action、否定、no-action ごとに集計し、日本語と英語も分ける。
- **Action name accuracy**: tool の選択（look / set_expression / nod）の正解率。
- **Slot accuracy / F1**: direction、amount、expression、count。
- **Sequence accuracy**: 複合 action の順序を含む一致。
- **No-action precision / recall**: 実行すべきでない入力を止める能力。
- **Confidence gate の効果**: gate による no-action への切り替え率と、誤作動率の変化。
- **Critical error rate**: 逆方向、否定無視、enum 外の値、未知 action、重複した呼び出し等。
- **Paraphrase consistency**: 同義表現で同じ canonical action を返す率。
- **Contrastive pair accuracy**: 否定の有無だけが違う対比ペアの、両方に正解した率。

### 評価条件の固定

同じ重みでも、評価条件で結果が大きく変わります。TinyLM-Bench では、Needle 2 と同じ重みの MimiModel が、prompt の組み立てと grammar の実装の違いから、厳格一致 3/16 に対して 1/16 でした（[`research_notes.md`](research_notes.md) §3.7）。そのため、次を固定して結果とともに記録します。

- Prompt template と system prompt。
- Decoding の設定。評価は greedy とし、乱数の影響をなくす。
- Grammar の実装と version。
- Confidence gate の閾値。
- 評価セットの version と hash。

Python の実装と C runtime は、同じ評価セットと同じ条件で比べます。

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
3. ESP32-S3 SIMD / ESP-DSP / ESP-NN / ESP-DL を使う quantized GEMV の比較。既存の runtime（esp32-llm の Xtensa PIE INT8 kernel、esp32-mind / esp32-ai の int4 PLE runtime）を流用できるかと、その license も調べる。
4. MQA/GQA、KV INT8、sliding window、recompute の速度・メモリ trade-off。
5. 日本語 Action dataset の品質の検証。v0 は M3 で作成・公開済み（[`data.md`](data.md)）。残りは、学習結果を見たうえでの人手の抜き取り確認、生成元の偏り、評価セットの難易度の確認。
6. Rule-based parser、小型 classifier、seq2seq との比較。ルールベースは M3 で測定済み（評価セットで 76.4%）。小型 classifier / seq2seq は未実施。
7. 既存の日本語 on-device tool-calling model、論文、製品、特許の網羅調査。公開されている小型モデル9種の Windows host での検証は、TinyLM-Bench で済んでいる（[`research_notes.md`](research_notes.md) §3.7）。
8. Grammar compiler の supported subset と code size。
9. Flash mmap、microSD streaming、external storage の latency。
10. OTA / rollback / recovery partition を残したまま成立する構成。
11. Servo safety、privacy、offline data retention の要件。
12. 開発者が求める latency と品質の水準。
13. Hugging Face の**モデルの** repository 名、商標、release packaging（データセットは `JapaneseTinyAgentLM-Action-Synth` で公開済み）。ライセンスは決定済み（重みとデータセットは CC BY-SA 4.0）。
14. （優先度低）ひらがなだけの入力と、漢字仮名交じり文の比較。入力はテキストのみと決まったので、ひらがなは頑健性の確認用の一部として評価するだけにする。

TTS（sanoTTS-jp）と ASR（Ralomi）に関する調査は、本計画の範囲外として外しました（2026-09-29）。

## 12. 最初の具体的な実験

最初の1サイクルは次に限定します。

1. （M2 で完了）Action schema v0 を `look` / `set_expression` / `nod` / no-action に絞る。形式は TinyLM-Bench と同じにし、1回の出力は 0〜2個とする（[`architecture.md`](architecture.md) §7）。
2. （M3 で完了）漢字仮名交じり文を主とした dataset を作る（ひらがなだけの入力は一部）。学習データは 2,000〜10,000件とし、否定と no-action をそれぞれ20%以上にする。multi-action、否定、no-action を独立したカテゴリにし、対比ペアを入れる。データはすべて CC BY-SA 4.0 と両立させ、出典を manifest に記録する。
3. Tokenizer を先に固定してから、3M と 5M を学習する（vast.ai 上）。実機には載せない上限参照として 20M も学習する。
4. Grammar なし/ありと confidence gate なし/ありで、カテゴリ別の exact match と no-action を比較する。
5. INT8 → INT4 の精度差を、カテゴリ別に測る。
6. TinyLM-Bench の共通評価で、既存モデル（Needle 2、FunctionGemma 270M、MimiModel）と比べる。
7. 5M INT4 を ESP32-S3 に載せ、Flash、PSRAM、tok/s、latency を測る。
8. 結果を見て、Action の改善を続けるか（10M Action、データの見直し）、完了条件を満たして Chat へ進むかを決める。

これにより、最も重要な「日本語 Action LM は小型化しても成立するか」を、Full pipeline の複雑さから切り離して検証できます。

最初の1周は、**Action 専用のスクラッチ学習**で行います。日本語の事前学習 corpus を選ぶと、そのライセンスがモデル重みのライセンスに直結するためです。corpus の選定を blocker にせず、Base の事前学習と SFT の比較（Phase 2 の Model axis）は corpus のライセンスが決まってから行います。

### 進捗（2026-09-29 時点）

| 項目 | 状態 |
|---|---|
| Private repository の作成、LICENSE（Apache-2.0）、`.gitignore` | 完了 |
| 設計文書（`docs/`） | 完了（本更新を含む） |
| B0 実機の初回調査 | 完了 |
| `.env` の `VAST_API_KEY` | 設定済み。認証と課金設定を確認済み |
| `.env` の `HF_TOKEN` | 設定済み。user `ayousanz` の write token で、`japanese-data-analyze` の admin であることも確認済み |
| M1 リポジトリ基盤 | **完了**（2026-09-29） |
| M2 Action schema v0 と評価の土台 | **完了**（2026-09-29） |
| M2.5 vast.ai 実行基盤 | **完了**（2026-09-29） |
| M3 合成データセット | **完了**（2026-09-29）。[Hugging Face で公開](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)（public、manual gate） |
| M4 Tokenizer と 3M / 5M / 20M の学習 | **完了**（2026-09-29）。下の「M4 の結果」 |
| Track B | B1、B3（計測）、B2.5 は **完了**、B2 は build まで完了（2026-09-29）。残りは servo の確認（ユーザーの立ち会いが必要）。結果は [`hardware.md`](hardware.md) §7–§10 |
| M5 grammar と量子化 | **完了**（2026-09-29）。grammar で致命的な誤りを 1/3 に、INT4 でも精度は落ちない。confidence gate は保留 |
| データ v0.3 / v0.4 | v0.3 は完了（3M で 91〜92%）。v0.4 は生成中 |
| M6 Host C runtime | 実装中（3M で出力が PyTorch と完全に一致） |
| vast.ai の費用（累計） | 約 $3.40（`runs/vast/*/run.json` の合計。M2.5〜M3 が約 $1.03、M4 が約 $0.24、M4 の後の量の確認・v0.3・v0.4 の生成と学習が、失敗した起動を含めて約 $2.13。実行中の v0.4b は含まない。2026-09-29 09:10 UTC 時点） |

### M1〜M3 の目的と完了条件

| # | 目的 | 完了条件 | 状態と結果 |
|---|---|---|---|
| M1 | 以降のコード（schema、評価、データ生成、学習）を、ローカルと vast.ai で同じ手順で再現できる環境で動かす | `uv sync --locked` と test がローカルで通る | **完了**。uv 0.12.20、Python 3.13、`uv.lock`（torch 2.14.0 は Windows が CPU 版、Linux が cu126 版）、ruff、pytest。`.env.example` は権限の設定で作成できず、変数は README と [`development.md`](development.md) §3 に記載 |
| M2 | 「正解」を機械的に判定できるようにし、M3 のデータ検査と、以降のすべての評価の土台にする | TinyLM-Bench の16件の期待値が validator と評価器を通り、座標規約の unit test が通る | **完了**。schema（`src/jtalm/action/action_schema_v0.json`）、validator（重複の禁止を含む）、正規化、角度への変換（`jtalm.action.mapping`）、評価指標（`jtalm.eval`）。39件の test が通過。評価器は TinyLM-Bench の厳格一致（Needle 2 が 3/16、FunctionGemma が 6/16、MimiModel が 1/16）を再現した（[`research_notes.md`](research_notes.md) §3.7） |
| M2.5 | vast.ai の GPU で、生成と学習を安全かつ再現可能に実行し、終わったら確実に削除できるようにする | 小さな生成と GPU 上の torch の動作確認で一連の流れが通り、instance の削除と費用が記録されている | **完了**。`jtalm.infra.job smoke` が RTX 3090（$0.153/h、driver 580、CUDA 13.0）で成功した。torch 2.14.0+cu126 で CUDA が使えることと、vLLM v0.30.0 による JSON 制約つきの生成を確認し、instance は自動で削除された（0.208 時間、約 $0.032）。1回目は、vLLM の image の `/root` の権限のせいで SSH が拒否されて失敗した（約 $0.023）。起動時（onstart）に権限を直すよう修正した。費用の合計は約 $0.055 |
| M3 | Action LM の学習データと評価セットを、規約上問題のない方法で作り、baseline を測って公開する | 評価セット 1,000件以上（重要カテゴリ各100件以上）、学習データ 2,000〜10,000件、manifest、rule-based baseline の数値、Hugging Face への公開（public、manual gate） | **完了**。詳細は下の「M3 の結果」 |

### M3 の結果（2026-09-29）

| 項目 | 結果 |
|---|---|
| 学習データ | train 9,067 件 + validation 477 件 = 9,544 件。negation 24.3%、no_action 24.5%（うち MASSIVE ja-JP 1,148 件）、multi_action 22.0%、single 17.3%、correction 12.0% |
| 評価セット | 1,189 件。single 335、multi_action 192、negation 270、no_action 337（うち MASSIVE test 150）、correction 55。英語 35 件、対比ペア 80 組 |
| 生成 | action-v0.2 の prompt。学習データは Qwen3-30B-A3B-Instruct-2507 が書いて温度 0 で検証し、評価セットは llm-jp-3.1-13b-instruct4 が書いて Qwen3 が検証した |
| ルールベースの baseline（評価セット） | 完全一致 76.4%。single 60.9%、multi_action 46.9%、negation 88.1%、no_action 99.1%、correction 76.4%。no-action の precision 0.80 / recall 0.94。対比ペアの正解率 0.84 |
| manifest | `datasets/manifests/action_v0.json`（件数、落とした理由の内訳、sha256、設定、3回の生成の記録、baseline の詳細） |
| 公開 | [`japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth`](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)。train 7,919 / validation 425 / test 1,039（合成の文だけで、MASSIVE は含めない）。public、manual gate、CC BY-SA 4.0 |

生成は3回行いました。

| 回 | 内容 | GPU | 時間 | 費用 | 結果 |
|---|---|---|---:|---:|---|
| 1（v0.1） | 学習データを llm-jp で検証 | A100 80GB | 0.496 h | $0.50 | llm-jp-3.1 が検証役として機能せず、残った件数が少なすぎた（学習データ 1,906 件） |
| 2（v0.2） | 指示を改善し、学習データを Qwen3 で検証 | A100 80GB | 0.352 h | $0.31 | 学習データ 8,540 件、評価セット 1,189 件。negation が 15.4% で目標に届かず |
| 3（追加） | 否定の spec を 9 → 21 に増やし、否定だけを追加で生成 | A100 80GB | 0.193 h | $0.17 | negation が 24.3% になり、すべての条件を満たした |

M4 で Action LM が超えるべき基準は、このルールベースの baseline（完全一致 76.4%）と、TinyLM-Bench の既存モデルの結果です。特に multi_action（46.9%）と single（60.9%）で、差をつける余地が大きくあります。

### M4 の結果（2026-09-29）

- **目的:** 3M / 5M の Action LM を学習し、ルールベースの baseline（76.4%）と既存モデルを上回れるかを確かめる。20M の上限参照と比べて、精度不足の原因（capacity か、data / tokenizer か）を切り分ける。
- **完了条件:** Tokenizer を固定して hash を記録する。3M / 5M / 20M の学習を vast.ai で完走する。評価セット 1,189件を greedy で生成し、カテゴリ別にルールベースと比べた表を作る。checkpoint、学習の記録、費用を残す。→ **すべて満たした。**

| 手順 | 結果 |
|---|---|
| 1. 学習データの転送 | `JobSpec.uploads` を追加した。Git の管理外のファイルを scp で送り、instance 上で sha256 を照合する（4 ファイルとも一致） |
| 2. Tokenizer | SentencePiece（unigram、byte fallback）の 2k / 4k / 8k を比べ、**2k（`action_v0_sp2048.model`、sha256 `61482f90…`）に固定**した。出力の JSON の固定の断片と enum の値を1 token にまとめたので、出力の token 数はどの語彙でも平均 4.7 で同じになり、入力側の指標だけで選べた。2k は、未知の日本語（MASSIVE の dev）での byte fallback が最も少なく（1.3%）、embedding が最も小さい（3M で全体の12%）。1件あたりの入力は約 8〜11 token。記録は `datasets/manifests/tokenizer_action_v0.json` |
| 3. モデル | decoder-only Transformer（RMSNorm、RoPE、GQA、SwiGLU、weight tying、bias なし）。3M = d192 × 7層（3.15M）、5M = d256 × 6層（5.05M）、20M = d384 × 12層（19.67M）。教師の出力は `name` を先に置いた compact な JSON（[`architecture.md`](architecture.md) §7）で、loss は出力と `</s>` だけにかける |
| 4. 学習 | vast.ai の Tesla V100 32GB（$0.219/h）。40 epoch、batch 64、AdamW、cosine。validation の完全一致（greedy）が最も高い checkpoint を採用した。1モデル 8〜14分 |
| 5. 評価 | 下の表。同じ checkpoint を手元の CPU で評価し直し、出力が1件残らず一致することを確認した |
| 6. 費用 | 1.085 h、約 $0.24（job の記録は `results/m4_action_v0/run.json`） |

評価セット（1,189件、完全一致 %。greedy、grammar なし、confidence gate なし）:

| model | 全体 | single | multi_action | negation | no_action | correction | 英語 | no-action P / R | 対比ペア |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ルールベース | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 / 94.2 | 83.8 |
| 3M | **84.4** | 62.1 | **79.7** | 98.5 | 99.1 | 76.4 | 54.3 | 86.1 / 98.8 | 58.8 |
| 5M（seed 0 / 1 / 2） | 79.6 / 82.0 / 81.3 | 54.9 / 59.1 / 55.8 | 68.2 / 73.4 / 74.5 | 98.1〜98.9 | 98.5〜99.7 | 60.0〜63.6 | 54.3 | 約 80 / 99 | 40.0〜51.2 |
| 20M | 83.9 | 63.0 | 77.6 | 97.0 | 99.1 | 74.5 | 54.3 | 83.2 / 98.2 | 52.5 |

TinyLM-Bench の16件（厳格一致）: 3M / 5M / 20M が 62.5〜68.8%。Needle 2（18.8%）、FunctionGemma 270M（37.5%）、MimiModel（6.2%）を上回った。ただし、ルールベースはこの16件で 100% になる。16件は、ルールを作るときに参照した例なので、参考値として扱う。

分かったこと:

1. **全体ではルールベースを上回った。** 特に multi_action（+33 point）と negation（+10 point）で差が大きい。validation（学習データと同じ Qwen3 が書いた文）では約 99% だが、別のモデル（llm-jp）が書いた評価セットでは 80〜84% になる。**生成元の違いによる差**が大きい。
2. **まだ届いていない条件:** single と correction はルールベースと同程度、英語（学習データにない）と対比ペアはルールベースより低い。目標値（完全一致 90%以上）にも届いていない。
3. **20M は 3M とほぼ同じ**（83.9% と 84.4%）。§12 の判断基準に照らすと、capacity ではなく **data の側の問題**である。5M の seed による差は ±1.2 point（79.6〜82.0%）。
4. **誤りの内訳（3M）:**
   - single の誤り 111件のうち **85件は、動作の依頼を `[]`（何もしない）と答えたもの**で、多くは確信度が高い（最小の token 確率が 0.99 以上）。学習データの正解の 48.8% が `[]`（no_action 24.5% と negation 24.3%）なので、見慣れない言い回しを `[]` に倒している。
   - 25件は、同じ call を2回出したもの（重複は schema で禁止）。重複を取り除くだけで、全体は 85.7%、single は 66.6%、correction は 78.2% になる。M5 の grammar で防げる。
   - correction では、「左は見なくていい」の否定された動作まで出す誤りや、方向を取り違える誤りがある。

### M4 の後の結果（2026-09-29）

M4 の後に、「データの量と多様さ」「grammar」「量子化」を順に確かめました。評価セット（1,189件）と評価の条件は、M4 から変えていません。

**1. データの量の確認**（`results/data_scaling_v0`）: 3M を v0 の学習データの 25% / 50% / 100% で学習しました（step 数はそろえ、seed は2つ）。

| 学習データ | 全体の完全一致（平均） |
|---|---:|
| 25%（約 2,300件） | 74.6% |
| 50%（約 4,500件） | 82.6% |
| 100%（9,067件） | 83.9% |

50% を超えると、ほとんど伸びません。**同じ書き手のデータを増やしても効かない**ので、次は多様さを増やしました。

**2. データ v0.3**（書き手を3つにして 18,071件。[`data.md`](data.md) §5、`results/v03_action`）:

| model | 全体 | single | multi | negation | no_action | correction | no-action P / R | 対比ペア |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ルールベース | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 0.80 / 0.94 | 83.8 |
| 3M（v0、M4） | 84.4 | 62.1 | 79.7 | 98.5 | 99.1 | 76.4 | 0.86 / 0.99 | 58.8 |
| **3M（v0.3、seed 0 / 1）** | **91.3 / 92.1** | 85.7 / 86.3 | 90.6 / 91.1 | 93.0 / 91.9 | 95.8 / 99.1 | 90.9 / 89.1 | 0.95 / 0.95〜0.96 | 85.0 / 85.0 |
| 5M（v0.3、seed 0 / 1） | 89.8 / 89.4 | 82.1 / 83.0 | 84.9 / 88.0 | 94.4 / 90.0 | 98.5 / 97.9 | 78.2 / 78.2 | 約 0.94 / 0.95 | 83.8 / 75.0 |
| 20M（v0.3） | 90.7 | 84.8 | 87.0 | 92.6 | 98.2 | 85.5 | 0.95 / 0.96 | 85.0 |

- 書き手を 1 → 3 にしたことで、3M は +7〜8 point 伸び、**全体の完全一致の目標（90%）を超えた**。multi、否定、no-action の precision の目標も満たした。no-action の recall は 94.6〜95.9% で、目標（95%）の前後。
- 5M と 20M は 3M を上回らない。精度の面でも、3M が実機の本命になる。
- negation は v0 の 98.5% から 92% 前後に下がった（動作ありの例を増やした影響と見られる）。英語は学習データにないので低い（参考値）。

**3. grammar と confidence gate**（M5 前半、`results/m5_grammar_on_m4`）: grammar は精度を変えずに、致命的な誤り（不正な出力と重複）を 2.6% から 0.8% に減らした（3M、v0）。confidence gate は精度を下げた（84.4% → 80.7%）。M4 のモデルは「確信を持って `[]` と答える」形で誤るため、確信度の低い出力を `[]` にする gate では直らない。また、validation が学習データと同じ書き手なので、閾値がほぼ 1 に選ばれてしまう。gate は、書き手の違う validation を用意してから調整し直す。

**4. 量子化**（M5 後半、`results/m5_quant_on_m4`）: 重みだけを INT8 / INT4（64個ずつの group、対称、fp16 の scale）にしても、精度は落ちない（3M: 84.4% → INT8 84.5%、INT4 84.8%。5M も ±0.4 point）。3M の INT4 は 1.68MB で、LM の予算（1.5〜5MB）に収まる。

**5. Host C runtime**（M6）: 実装中。3M の FP32 / INT8 / INT4 のそれぞれで、grammar なし・ありのどちらでも、評価セットの 1,189件すべてで出力が PyTorch と一致した。tokenizer も、学習データ、validation、評価セットの全件と、無作為な 2万件で一致した。

### 次の計画（2026-09-29）

| 順 | 作業 | 状態 |
|---|---|---|
| 1 | データ v0.4: 書き手を 7 つにして約 5 万件に増やす（ABEJA-Qwen2.5-32B-Japanese、Mistral-Nemo-Japanese、granite-3.3-8b、ELYZA-Shortcut-32B、calm3、sarashina2.2、Qwen3） | 生成中（1回目は host の disk 不足で3つの書き手が失敗。成功した4つは回収して、`gen_action_v04b` で残りを生成中） |
| 2 | v0.4 で 3M / 5M / 20M を再学習し、v0 / v0.3 / v0.4 の曲線から、**データ量とモデルサイズの候補**を決める | v0.4 の生成の後 |
| 3 | 採用するモデルを INT8 / INT4 で確認する | 手順は完成済み |
| 4 | M6 の完了（5M の parity、文書） → B4（実機への移植と速度の計測） → **モデルサイズの最終決定** | M6 は実装中 |
| 5 | servo の確認（B2）: ユーザーの立ち会いのもとで行う | 手順は [`hardware.md`](hardware.md) §10 |

- 英語は学習データに入れていないので、完了条件の判定では参考値として扱う（完全一致の全体の値には含まれる）。

**Track B の状況（2026-09-29）:**

- M4 と並行して、B1 → B3 → B2.5 → B2 の準備の順に進めている。Docker Desktop は起動済み。
- 第三者のコード（`stackchan-idf`、`esp32-llm`、それらが指定する依存物）の取得、build、実機への書き込みは、ユーザーの明示的な許可を得て行う（2026-09-29）。取得したコードは Git の管理外に置く。
- **B2:** `stackchan-idf` を書き込むと、受領時の firmware が上書きされる。B0 のバックアップ（[`hardware.md`](hardware.md) §6）から戻せる。servo を実際に動かす確認は、ユーザーの立ち会いのもとで行う。

### Track A: PC 上の実装マイルストーン

| # | マイルストーン | 成果物 | 完了条件 |
|---|---|---|---|
| M1 | リポジトリ基盤 | `pyproject.toml` / `uv.lock`（`uv add` のみ）、pytest、ruff、`.env.example`（権限の設定で作成できず、[`development.md`](development.md) §3 の表で代替）。Python は PyTorch 2.14 系と SentencePiece の wheel がそろう版に固定する（第一候補は 3.13） | `uv sync --locked` と test がローカルで通る |
| M2 | Action schema v0 と評価の土台 | `src/jtalm/action/action_schema_v0.json`（TinyLM-Bench と同じ形式、0〜2個）、validator、正規化処理、評価指標（カテゴリ別の exact match、slot、no-action の precision / recall、critical error）、カテゴリから角度への変換表 | TinyLM-Bench の16件の期待値が、validator と評価器を通る。K151 の座標規約（[`architecture.md`](architecture.md) §7）に沿った unit test が通る |
| M2.5 | vast.ai 実行基盤 | `src/jtalm/infra/`（`uv run python -m jtalm.infra.job <job> --approve-dph <上限>`。GPU の検索 → instance 作成 → `git archive` で転送 → `uv sync --locked` → 各手順 → 回収 → 必ず削除 → 費用の記録）。CLI は `uv add --dev vastai`（1.8 系）で lock する。vLLM（`vllm/vllm-openai:v0.30.0`）を使う生成用の構成を含める | 小さな生成と、GPU 上での torch の動作確認で一連の流れが通り、instance の削除と費用が記録されている（学習そのものの確認は M4 で行う） |
| M3 | Dataset v0 と baseline | vast.ai 上で、正解を先に決めた spec から、Apache-2.0 のオープンモデルに文を書かせ、別のモデルで検証した合成データ（学習データは Qwen3-30B-A3B-Instruct-2507 が書き、同じモデルが温度 0 で検証する。v0.1 の llm-jp-3.1 による検証は機能しなかったため変更した。評価セットは llm-jp-3.1-13b-instruct4 が書き、Qwen3 が検証する）。学習データは 2,000〜10,000件（漢字仮名交じり文が主で一部ひらがな、言い換え、multi-action、否定と no-action を各20%以上、対比ペア）。少量の英語の命令は評価セットにだけ入れる。負例には MASSIVE（ja-JP）も使う。ルールベース parser、既存モデルの結果（TinyLM-Bench）、dataset manifest。合成データは Hugging Face に public、manual gate で公開する（[`data.md`](data.md)） | 評価セットが1,000件以上で、重要カテゴリ（multi-action、否定、no-action）が各100件以上ある。生成元（モデルと prompt）で学習データと評価セットを分け、重なりを除いて、baseline の数値が出ている。全データの出典とライセンス（CC BY-SA 4.0 と両立すること）が manifest に記録されている。学習データの中身に Claude や ChatGPT の出力が含まれていない |
| M4 | Tokenizer と 3M / 5M / 20M の学習 | SentencePiece（2k / 4k / 8k を比較し、coverage、byte fallback 率、token 長で選ぶ）、decoder-only Transformer、学習 script、PC だけの上限参照（20M） | **Tokenizer を固定してから**本学習を始める。ローカルの CPU smoke test を通してから、vast.ai 上で学習を完走する。**完了**（2026-09-29。§12「M4 の結果」） |
| M5 | Grammar 制約、confidence gate、量子化 | grammar-constrained decoding（Python）、confidence gate、INT8 / INT4 の fake quant、比較表 | §12 冒頭のリストの手順 4〜6 の比較結果が、固定した評価条件（§10）でカテゴリ別に揃っている |
| M6 | Host C reference runtime | portable C の推論コード、golden vector。日本語の入力は UTF-8 のファイルか stdin で渡す（argv は使わない） | PyTorch の出力と token が一致し、同じ評価セットで Python の実装と同じ結果になる |

M3 の評価セットを学習データとは別のモデルと別の prompt で作るのは、同じ生成元のデータで評価すると、生成のくせを暗記しているだけで高得点になるためです。評価セットは評価だけに使い、学習には使いません。

### Track B: 実機上のマイルストーン

| # | マイルストーン | 内容 |
|---|---|---|
| B0 | 実機の初回調査 | **完了**（2026-09-29）。対象機の特定、SoC / Flash / PSRAM、Flash 全体のバックアップ（[`hardware.md`](hardware.md)） |
| B1 | ESP-IDF の build 環境 | ESP-IDF **v5.5.5** の公式 Docker image（`espressif/idf:v5.5.5`）で build する。ローカルへの導入は不要。書き込みは Windows から `esptool` で行う。**完了**（2026-09-29） |
| B2 | Servo の座標の確認 | K151 に対応した `stackchan-idf`（v5.5.5 で検証済み）を build して書き込み、yaw の符号と pitch の中立角度を確認する。**build まで完了**。起動直後から首が動くので、書き込みと確認はユーザーの立ち会いのもとで行う（手順は [`hardware.md`](hardware.md) §10、5〜10分） |
| B2.5 | 既存 runtime による実機の基準値 | TinyLM-Bench の CoreS3 計画（92）に沿い、既存の小さな runtime を K151 で動かす。まず esp32-llm stories260K（FP32、1.06MB）で起動と 100 token の連続生成を確かめる。次に **stories3M INT8**（3.1M params、3.35MB）で、tok/s と Quad PSRAM の帯域を測る。上流の約 12 tok/s との差も見る。本プロジェクトの 3M / 5M に近い規模なので、自前の runtime の目標速度と、モデル規模の判断に使う。**完了**（2026-09-29）: stories3M INT8 は forward だけで 6.5〜7.1 tok/s（上流の約半分。CoreS3 は Quad PSRAM のため） |
| B3 | LM 評価用の最小 firmware | LM runtime の枠組み、servo 制御、計測用の telemetry だけを持つ自前の firmware を作る。Flash map と状態ごとの SRAM / PSRAM の peak を測り、LM の予算を確定する（Phase 0 の exit gate）。**計測の部分は完了**（2026-09-29、`firmware/jtalm_eval/`）: 起動直後の内部 SRAM 空き 335,663 B、PSRAM 空き 8.39MB、14MB の `model` partition を1回で mmap、読み出しは PSRAM 32.8 MB/s、Flash の mmap 31.2 MB/s。servo と画面を載せた状態の計測は B4 で行う |
| B4 | ESP32 への移植 | M6 の C runtime を B3 の firmware に載せ、5M INT4 の tok/s、latency、PSRAM の peak を測る。Action を servo の命令に変換して実際に動かす |

B2 以降は、実機の firmware を書き込む前に必ずバックアップを取ります（[`development.md`](development.md) §5）。

### 判断ポイント

M5 と B4 の結果が揃った時点で、次のどちらへ進むかを決めます。

- **Action LM が完了条件（§4 の目標値と、既存モデルへの勝利）と実機の基準（Phase 4）を満たした場合:** Action LM を公開し、10M Chat（Base の事前学習を含む）へ進む。
- **精度が足りない場合:** 20M の上限参照と比べて原因を切り分ける。
  - 20M が大きく上回る場合は、capacity が足りないと判断し、10M Action を試す。
  - 20M も低い場合は、data か tokenizer の問題と判断し、そちらを見直す。
- **速度:** B2.5 で測った stories3M INT8 の実機速度（forward だけで約 7 tok/s）を基準にし、5M / 10M を実機に載せたときの latency を見積もって、規模の判断に使う。重みを毎 token 読む前提では、速度の上限は約 32 MB/s ÷ 重みの byte 数（B3）なので、INT4 化、入力のまとめ処理（batch prefill）、KV cache の小型化が効く。

## 13. 工数の見積もり（Claude Code が実行する前提）

実装、学習、評価、実機での計測は、すべて Claude Code が実行します（[`README.md`](README.md) §1）。見積もりは次の3つに分けています。

- **Claude Code の作業時間:** 実装、test、debug を含む。
- **学習と待ち時間:** GPU での学習や、image の取得などの待ち時間。
- **ユーザーの確認:** Claude Code だけでは完了できない点。

初回の見積もりなので、±50% 程度の幅があります。精度が目標に届かなかったときの反復（データや tokenizer の見直し）は、この表には含みません。

### Action LM の1周目

| # | 内容 | Claude Code の作業時間 | 学習と待ち時間 | ユーザーの確認 |
|---|---|---:|---|---|
| M1 | リポジトリ基盤 | 1〜2 h | — | uv の更新 |
| M2 | Action schema v0 と評価の土台 | 2〜3 h | — | — |
| M2.5 | vast.ai 実行基盤 | 2〜4 h | 小さな生成と GPU 上の torch の確認 10〜30 分 | 費用の承認（API key は設定済み） |
| M3 | Dataset v0 と baseline | 5〜9 h | GPU での生成 1〜3 時間 | 費用の承認、**Hugging Face へのアップロード直前の最終確認**（`HF_TOKEN` は設定済み） |
| M4 | Tokenizer と 3M / 5M / 20M の学習 | 4〜6 h | GPU で数時間 | 費用の承認 |
| M5 | Grammar、confidence gate、量子化 | 3〜5 h | — | — |
| M6 | Host C reference runtime | 4〜8 h | — | — |
| B1 | ESP-IDF の Docker 環境 | 0.5〜1 h | image の取得 | Docker Desktop の起動 |
| B2 | Servo の座標の確認 | 1〜2 h | — | **servo の動きを目で確認し、安全のため立ち会う** |
| B2.5 | 既存 runtime による実機の基準値 | 2〜4 h | — | — |
| B3 | LM 評価用の最小 firmware | 3〜5 h | — | — |
| B4 | 実機への移植と servo の制御 | 4〜8 h | — | **Servo の動作に立ち会う** |
| 合計 | | **約 32〜57 h** | GPU で数時間 | |

### M1〜M4 の実績（2026-09-29）

| # | Claude Code の作業時間 | GPU と費用 | 見積もりとの差 |
|---|---|---|---|
| M1 | 未記録 | — | — |
| M2 | 未記録 | — | — |
| M2.5 | 未記録 | RTX 3090 で 0.208 h（ほかに失敗 1回、0.105 h）。計 約 $0.055 | SSH の失敗（vLLM の image の権限）の修正が加わった |
| M3 | 未記録 | A100 80GB で 3回、計 約 1.04 h。$0.50 + $0.31 + $0.17 = 約 $0.98 | 見積もりの前提外だった反復（v0.1 の失敗、否定の追加生成）を含む |
| M4 | 約 1.3 h（05:33〜06:53 UTC。実装と CPU の smoke test が約 10 分、GPU の job の待ちが約 65 分、分析と記録が約 5 分） | Tesla V100 32GB で 1.085 h、約 $0.24（5モデルの学習と評価） | 見積もり（4〜6 h、GPU で数時間）より大幅に短かった |
| Track B（B1、B3、B2.5、B2 の build） | 約 1 h（06:27〜07:26 UTC、担当 agent が M4 と並行して実行） | — | 見積もり（B1〜B3 と B2.5 で 5.5〜11 h）より大幅に短かった |
| 合計 | — | 約 $1.27 | GPU の時間は、見積もり（数時間）より短かった |

M1〜M3 の Claude Code の作業時間は計測していないため、「未記録」としています。M4 からは、主な手順の開始と終了の時刻を記録しています。

### 速く進めるための並行化

最短の経路（critical path）は M1 → M2 → M2.5 → M3 → M4 → M5 → M6 → B4 です。

- GPU で学習している間（M4）に、Track B の B1〜B3 と B2.5 を進める。
- 実機の作業のうち、ユーザーの立ち会いが要るのは B2 と B4 の servo の確認だけ。まとめて行えば、待ちを減らせる。
- 暦の上での日数は、セッションを開ける時間と、上の確認のタイミングで決まる。

### Chat LM（Action の完了後）

| 内容 | Claude Code の作業時間 | 学習と待ち時間 | ユーザーの確認 |
|---|---:|---|---|
| 事前学習の corpus の準備（例: 日本語版 Wikipedia、CC BY-SA 4.0） | 3〜6 h | download と前処理 | corpus の承認 |
| Base の事前学習（10M） | 2〜4 h | GPU で数時間 | 費用の承認 |
| Chat の SFT のデータと学習 | 4〜8 h | GPU で1時間程度 | データの作り方の承認 |
| 評価（自動評価、LLM による判定） | 3〜5 h | — | 人による比較評価（human preference）の一部 |
| 合計 | **約 12〜23 h** | GPU で数時間 | |

公開（Phase 7）の準備（モデルカード、artifact、checksum、審査の項目）には、別に 2〜4 h を見込みます。公開してよいかの最終判断は、ユーザーが行います。
