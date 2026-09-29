# JapaneseTinyAgentLM 設計資料

最終更新: 2026-09-29

## 1. 目的とゴール

### 目的

M5Stack CoreS3 のような **16MB Flash / 8MB PSRAM** クラスのマイコン上で、ネットワークに依存せず日本語テキストを処理できる超小型モデルを、**実用のために**作ります。

開発と評価に使う実機は、M5Stack 公式の **M5 スタックチャン（SKU K151）** です。本体は CoreS3 で、servo は Feetech SCS0009 を2個使います。詳細は [`hardware.md`](hardware.md) を参照してください。

狙いは「大規模な汎用チャットモデルを無理に縮小すること」ではありません。TinyLM-Bench の検証で、既存の小型モデルには次の4つを同時に満たすものがないと分かりました（[`research_notes.md`](research_notes.md) §3.7）。本プロジェクトはこの空白を埋めます。

- 日本語を理解できる
- ESP32 に載る大きさである
- 厳密な Action を出力できる
- 安全に no-action を返せる

### ゴール（2026-09-29 確定）

| 項目 | 内容 |
|---|---|
| 位置づけ | **実用**のためのモデル。研究としての比較は、実用に必要な範囲で行う |
| 利用者 | Stack-chan などに組み込んで使う**開発者**。組み込みやすさ、仕様の明確さ、再現性を重視する |
| 入力 | **テキストのみ**。主な対象は漢字仮名交じりの日本語で、英語の命令は評価用に少量だけ扱う |
| 作る順序 | ① **Japanese Action LM** を K151 の実機で完成させる → ② **Japanese Tiny Chat LM** に取り組む |
| 公開 | モデルは Hugging Face の [`ayousanz`](https://huggingface.co/ayousanz)、合成データセットは organization [`japanese-data-analyze`](https://huggingface.co/japanese-data-analyze) で公開する。どちらも **CC BY-SA 4.0**（商用利用可）。合成データセットは public、manual gate。モデルは公開の前にユーザーの確認を取る |
| 学習データ | Apache-2.0 のオープンモデルと、ライセンスが両立する既存データで作る。Claude Code は、コードの作成と実行だけを担当する（[`data.md`](data.md)） |
| 期限 | 決まっていない。できるだけ早く作る |
| 実行体制 | 実装、学習、評価、実機での計測は、すべて **Claude Code** が実行する。学習と合成データの生成は vast.ai で行う。工数は Claude Code の作業時間で見積もる（[`roadmap.md`](roadmap.md) §13） |

| 派生モデル | 入力 | 出力 | 主用途 | 順序 |
|---|---|---|---|---|
| Japanese Action LM | 日本語 text | Action の JSON（0〜2個、`[]` は no-action） | サーボ（視線、うなずき）と表情の制御。対象外や曖昧な入力には no-action を返す | 1 |
| Japanese Tiny Chat LM | 日本語 text | 短い日本語 text | 短い応答、簡単な会話、状態に応じた発話文の生成 | 2 |

**Action LM の完了条件（暫定。[`roadmap.md`](roadmap.md) §4）**

- 完全一致 90%以上、否定と multi-action それぞれ 90%以上、no-action の recall 95%以上と precision 0.90以上、schema 妥当 100%
- 既存の小型モデル（Needle 2、FunctionGemma 270M、MimiModel）に、厳格一致率で勝つ
- M3 の評価セット（1,189件）で、ルールベースの baseline（完全一致 76.4%）を、全体とカテゴリ別の両方で上回る
- 量子化後も精度を保ち、host の C 実装と一致し、K151 の実機で容量、速度、安定性の基準を満たし、servo を実際に動かす

**公開物（Hugging Face と GitHub）**

- Hugging Face（`ayousanz`）: FP の checkpoint、ESP32 向けの量子化 artifact、tokenizer、モデルカード、評価結果（公開前にユーザーが確認する）
- Hugging Face（`japanese-data-analyze`、dataset）: 合成データセット。public、manual gate、CC BY-SA 4.0。**2026-09-29 に公開済み**（[`data.md`](data.md) §6）
- GitHub: 学習と評価の code、ESP32 runtime

開発者向けの追加の公開物として、次の2つがあります。これらは**モデルが完成してから判断します**。まずはモデルを作ることを優先します。

- ESP-IDF の component としての runtime
- Tool を追加するための、データ生成と fine-tuning の手順（recipe）

### 答えたい問い

- 日本語の短い命令理解と Action 生成は、何百万 parameter まで小型化できるか。
- 日本語の短い会話に最低限必要なモデル規模はどの程度か。
- 共通 Base / Tokenizer / Runtime により、Chat と Action の重複をどこまで減らせるか。
- 16MB Flash / 8MB PSRAM の CoreS3 で、LM に割り当てた予算（[`architecture.md`](architecture.md) §9–10）の中で、どこまでの品質と速度を出せるか。

入力をテキストのみとしたので、「ひらがなで直接入力すると小型化に有利か」という問いは中心から外しました（[`research_notes.md`](research_notes.md) §5）。

## 2. スコープ

### 含むもの

- 日本語 Base LM の学習
- Chat SFT と Action SFT
- 日本語向け小語彙 Tokenizer
- 3M / 5M / 10M / 20M 規模の比較
- INT8 / INT4、および必要に応じた 2〜3bit 量子化実験
- ESP32-S3 向け推論 Runtime
- KV cache と workspace の省メモリ化
- JSON / Action grammar-constrained decoding
- Host と実機での再現可能な評価
- 将来の Unified Chat + Action Model

### 含まないもの

- 音声波形を直接入力する end-to-end 音声言語モデル
- Vision encoder や画像・映像理解
- ASR 自体の開発（`ayutaz/Ralomi` が担当）
- TTS 自体の開発（`sanoTTS-jp` 等が担当）
- ASR / TTS との同居の検証と統合（将来の別計画。2026-09-29 決定）
- Stack-chan の Servo / Face / Audio driver の再実装
- ChatGPT 相当の世界知識、長文生成、汎用推論
- 現時点での製品化・安全認証・市場性の断定

## 3. プロジェクト構造に関する決定

Chat と Action は、重みと評価目的が異なるため、最初は別 checkpoint とします。ただし、次は共通化します。

- 学習用の Base architecture
- Tokenizer と vocabulary
- 日本語事前学習 corpus pipeline
- checkpoint / quantization / export 形式
- Host reference inference
- ESP32-S3 Runtime、演算 kernel、KV cache
- 品質・速度・メモリ計測 framework

```text
Japanese Base LM
       │
       ├── Chat SFT ─── Japanese Tiny Chat LM
       │
       └── Action SFT ─ Japanese Action LM
                              │
                              └── grammar-constrained decoding

検証後:

Japanese Unified LM
       ├── <chat>   → Japanese text
       └── <action> → JSON / actions
```

この順序にする理由は、最初から multitask 化すると、性能不足の原因が Base、Tokenizer、Chat data、Action data、model size、multitask interference のどれか判別しにくくなるためです。

## 4. VLA ではない理由

VLA は通常 **Vision-Language-Action** を指し、画像または映像をモデル入力として直接処理する構成です。本プロジェクトのモデル入力は日本語テキストだけで、カメラ画像を入力しません。

したがって、現時点での適切な分類は次のいずれかです。

- Japanese Tiny Language Model
- Language-to-Action Model
- Action LM
- Tool-Calling LM
- Task-oriented Semantic Parser
- MCU-oriented Japanese Agent LM（プロジェクト全体の説明として使用）

Stack-chan がカメラを搭載していても、カメラが model graph に接続されていない限り VLA とは呼びません。将来 Vision encoder を追加した場合は別途 VLA branch として再定義します。

## 5. 参考: 将来の ASR / TTS との統合（本計画の対象外）

本計画の入力は UTF-8 のテキストのみで、Ralomi（ASR）にも sanoTTS-jp（TTS）にも依存しません（2026-09-29 決定）。この節は、将来の別計画のための記録として残しています。

`ayutaz/Ralomi` は、ESP32-S3 向け日本語 ASR を目指す別プロジェクトです。本プロジェクトとは repository、学習目的、artifact、評価指標を分離します。

```text
音声波形
  ↓
Ralomi（ASR、別プロジェクト）
  ↓  日本語 text / 正規化ひらがな / モーラ列
JapaneseTinyAgentLM
  ├─ Chat   → 日本語 text → TTS
  └─ Action → JSON         → Servo / Face / Sensor
```

会話で確認した Ralomi の現状は以下です。ただし、Ralomi repository は非公開・実験段階であり、2026-09-29 の匿名 Web 参照では 404 でした。公開済み・完成済み・性能保証済みとは扱いません。

- 40次元 log-Mel を入力とする小型音響モデルを検討中。
- CTC / RNN-T 系を候補とし、モーラ token から正規化ひらがなを返す契約を検討中。
- release architecture は未確定。
- INT8 M6 は精度 gate で停止中という会話時点の情報がある。
- Artifact 予算案は Tiny 約2MB以下、Standard 約8MB以下、Large 約16MB以下。ただし合格済みモデルの実測サイズではない。
- Stack-chan では Tiny 相当、最大発話 5〜8秒、W8A8、PSRAM peak 2.5MB 以下を初期目標候補とする。

Ralomi の仕様や進捗は、LM の開発の blocker にしません。

## 6. 文書の読み方

- [`architecture.md`](architecture.md): モデル構成、Action schema、Runtime、Flash/PSRAM 設計
- [`hardware.md`](hardware.md): 対象の実機（K151）の構成、初回調査（B0）の計測値、Flash のバックアップ
- [`development.md`](development.md): uv、vast.ai、認証情報、実機操作の運用ルール
- [`data.md`](data.md): 学習データの方針、規約の調査結果、使うデータと生成モデル、合成データの公開方法
- [`research_notes.md`](research_notes.md): 先行例、比較、差別化、市場・新規性の仮説
- [`roadmap.md`](roadmap.md): 実装順、マイルストーン、評価、gate、今後の調査項目

## 7. 記述の確度

本文では情報を次の5段階で扱います。

| ラベル | 意味 |
|---|---|
| 確認済み | 公式仕様または一次ソースで再確認した事項 |
| 実測 | 実機で読み取り・計測した値。計測条件（firmware、設定など）を必ず併記する |
| 会話時点 | 参照会話で調査されたが、この文書作成時に独立再検証していない事項 |
| 設計目標 | 今後の実装・評価で達成を目指す値 |
| 仮説 | 実験、市場調査、先行研究調査が必要な主張 |

数値が「目標」または「仮説」の場合、実測値として引用してはいけません。「実測」の値も、併記した条件以外に一般化してはいけません。

## 8. 決定事項の記録

| 日付 | 決定 | 詳細 |
|---|---|---|
| 2026-09-29 | ソースコードと文書のライセンスを Apache License 2.0（Copyright 2026 ayutaz）とする。データと重みは別途決める（→ 同日、重みと合成データセットは CC BY-SA 4.0 に決定） | [`../LICENSE`](../LICENSE) |
| 2026-09-29 | GitHub の private repository `ayutaz/JapaneseTinyAgentLM` で管理する | — |
| 2026-09-29 | 学習は vast.ai で行う。API key は `.env` の `VAST_API_KEY` から読む | [`development.md`](development.md) §3–4 |
| 2026-09-29 | Python は uv で管理し、依存の追加は `uv add` だけを使う（`uv pip` は使わない） | [`development.md`](development.md) §2 |
| 2026-09-29 | 対象の実機を M5 スタックチャン K151 とする | [`hardware.md`](hardware.md) |
| 2026-09-29 | Action の yaw は正の値を右とする（公式 firmware の規約。実機での確認は未実施） | [`hardware.md`](hardware.md) §3 |
| 2026-09-29 | PC 上の実験（Track A）と実機での計測（Track B）を並行して進める。最初の1周は Action 専用のスクラッチ学習とし、Base の事前学習は corpus のライセンスが決まってから行う | [`roadmap.md`](roadmap.md) §12 |
| 2026-09-29 | 本計画の範囲は **LLM を作ること**に限る。TTS / ASR の調査と同居の検証は行わない。LM は LM 用の Flash / PSRAM 予算だけを前提に開発する | [`roadmap.md`](roadmap.md) §1、[`architecture.md`](architecture.md) §9–10 |
| 2026-09-29 | 実機の build は ESP-IDF v5.5.5（Docker image `espressif/idf:v5.5.5`）に固定する。LM の評価には自前の最小 firmware を使う | [`development.md`](development.md) §7 |
| 2026-09-29 | Action schema v0 は TinyLM-Bench と同じ `{"name","arguments"}` の配列にする。方向と量はカテゴリで表し、1回の出力は 0〜2個、`[]` を no-action とする。Action は `look` / `set_expression` / `nod` の3種類で、`speak` は外す。角度への変換は firmware 側で行う | [`architecture.md`](architecture.md) §7 |
| 2026-09-29 | 日本語を主とし、英語の命令は評価用に少量だけ扱う | [`architecture.md`](architecture.md) §2 |
| 2026-09-29 | 量子化後の LM の容量は 1.5〜5MB とする（TinyLM-Bench の検証メモにあった 4〜8MB は採らない）。語彙サイズは 2k〜16k を実測で比べて決める | [`architecture.md`](architecture.md) §3–4 |
| 2026-09-29 | Grammar に加えて confidence gate を入れ、確信度の低い出力は no-action にする | [`architecture.md`](architecture.md) §8 |
| 2026-09-29 | Action の目標値は、TinyLM-Bench の検証メモの値（完全一致 90%以上、no-action 95%以上など）を暫定で採用し、既存モデルを baseline に加える | [`roadmap.md`](roadmap.md) §4 |
| 2026-09-29 | TinyLM-Bench の検証全体（00 / 02 / 90 / 91 / 92）を反映する。主な内容は次のとおり。Action の契約（入力は1〜2文、出力は0〜2個、tool は v1 で 8〜16 種類）。学習データは 2,000〜10,000件で、否定と no-action を各20%以上とし、対比ペアを入れる。Tokenizer を先に固定する。PC 上だけの上限参照（20M）を置く。評価条件（prompt、greedy、grammar の実装）を固定して記録する。量子化後はカテゴリ別に評価し直す。既存 runtime（esp32-llm stories3M INT8）で実機の基準値を取る（B2.5） | [`roadmap.md`](roadmap.md) §4、§10、§12、[`architecture.md`](architecture.md) §2–7 |
| 2026-09-29 | **ゴールを確定する。** 実用のためのモデルとし、利用者は開発者とする。入力はテキストのみとする。Action LM を実機で完成させてから Chat LM に取り組む。期限は設けず、できるだけ早く作る。実装と学習はすべて Claude Code が実行する | 本文書 §1 |
| 2026-09-29 | モデルの重みは Hugging Face で **CC BY-SA 4.0**（商用利用可）で公開する。学習データは CC BY-SA 4.0 と両立するものだけを使う | [`development.md`](development.md) §6 |
| 2026-09-29 | まずモデルを作ることを優先する。開発者向けの追加の公開物（ESP-IDF の component、fine-tuning の手順）は、モデルが完成してから判断する | 本文書 §1、[`roadmap.md`](roadmap.md) §9 |
| 2026-09-29 | 学習データの中身は、Apache-2.0 / MIT のオープンモデル（学習データは Qwen3 と予備の gpt-oss、評価セットは llm-jp-4.1）と、ライセンスが両立する既存データ（MASSIVE など）で作る。Claude Code はコードの作成と実行だけを担当し、文章やラベルは書かない。Codex（ChatGPT のプラン）はデータの中身の作成に使わない （→ M3 で、評価セットは llm-jp-3.1、学習データの検証は Qwen3 に変更。下の行） | [`data.md`](data.md) §1–2 |
| 2026-09-29 | 合成データは vast.ai 上で生成し、Hugging Face に public、manual gate でアップロードする | [`data.md`](data.md) §5–6 |
| 2026-09-29 | Hugging Face の公開先は organization `japanese-data-analyze` とする。合成データセットのライセンスは CC BY-SA 4.0 とする | [`data.md`](data.md) §6、[`architecture.md`](architecture.md) §13 |
| 2026-09-29 | M3 の実行結果による変更。評価セットは llm-jp-3.1-13b-instruct4 が書く（llm-jp-4.1 は thinking 版しかないため）。学習データは Qwen3-30B-A3B-Instruct-2507（bf16）が書き、温度 0 で検証する（llm-jp-3.1 は検証役として機能しなかったため）。否定の spec を 21 通りに増やし、否定だけを追加で生成する | [`data.md`](data.md) §3、§5 |
| 2026-09-29 | 合成データセットを [`japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth`](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth) として公開した（public、manual gate、CC BY-SA 4.0） | [`roadmap.md`](roadmap.md) §12 |
| 2026-09-29 | 開発環境を固定する。Python 3.13、torch 2.14.0（Linux は cu126、Windows は CPU 版）、vLLM の image は `vllm/vllm-openai:v0.30.0`、依存は `uv.lock` で固定し、instance では `--no-dev` を使う | [`development.md`](development.md) §2、§4 |
| 2026-09-29 | 学習データと評価セットは、テンプレート単位ではなく生成元（モデルと prompt）で分ける。キーワードの規則で正解を確かめる検査は入れない（入れると、ルールベースの baseline が不当に高くなるため） | [`data.md`](data.md) §5 |
| 2026-09-29 | Action LM の完了条件に、ルールベースの baseline（評価セットで完全一致 76.4%）を全体とカテゴリ別で上回ることを加える。M4 の GPU 費用は、あらためて承認を得る | [`roadmap.md`](roadmap.md) §4、§12 |
| 2026-09-29 | M4 の決定。Tokenizer は SentencePiece の 2k（unigram、byte fallback）に固定し、出力の JSON の固定の断片と enum の値を1 token にまとめる。教師の出力は `name` を先に置いた compact な JSON にする。学習データなど Git の管理外のファイルは、job runner が scp で送り、sha256 で照合する | [`roadmap.md`](roadmap.md) §12、[`architecture.md`](architecture.md) §7 |
| 2026-09-29 | M4 の結果（3M 84.4%、20M 83.9%）から、精度不足の原因は capacity ではなく data の側と判断する。次は M5 の grammar と、学習データ v0.3（書き手と言い回しを増やし、`[]` の割合を下げる）。目標値は据え置き、no-action の precision 0.90 以上を加える。英語は参考値とする | [`roadmap.md`](roadmap.md) §4、§12 |
| 2026-09-29 | Track B で、第三者のコード（`stackchan-idf`、`esp32-llm` と、それらが指定する依存物）を取得して build し、実機に書き込むことを、ユーザーが明示的に許可した | [`hardware.md`](hardware.md) |
| 2026-09-29 | Hugging Face に公開する repository（データセットとモデル）は、すべて Community contributions（Discussions と Pull Requests）を off にする。公開済みのデータセットにも設定した | [`data.md`](data.md) §6、[`development.md`](development.md) §6 |
| 2026-09-29 | モデルの公開先はユーザーのアカウント [`ayousanz`](https://huggingface.co/ayousanz) に変更する（データセットは `japanese-data-analyze` のまま）。モデルを公開する前には必ずユーザーの確認を取る | [`architecture.md`](architecture.md) §13 |
| 2026-09-29 | 学習データは v0.4（書き手7つ、47,450件）を採用する。モデルサイズは、精度の面では 3M（INT4）を第一候補とし、B4 の実機速度を見て最終決定する | [`roadmap.md`](roadmap.md) §12 |
