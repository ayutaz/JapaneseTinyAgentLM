# JapaneseTinyAgentLM

ESP32-S3 / M5Stack CoreS3 上でネットワークなしに動く、**実用のための**日本語の超小型言語モデルを作るプロジェクトです。完成したモデルは Hugging Face の [`ayousanz`](https://huggingface.co/ayousanz) で、合成データセットは organization [`japanese-data-analyze`](https://huggingface.co/japanese-data-analyze) で公開します（モデルの公開は、ユーザーの判断で保留中です）。

## ゴール

| 項目 | 内容 |
|---|---|
| 位置づけ | 研究のためではなく、**実用**のためのモデル |
| 利用者 | Stack-chan などに組み込んで使う**開発者** |
| 入力と出力 | 入力は**テキストのみ**（漢字仮名交じりの日本語）。出力は Action の JSON、または短い日本語の応答 |
| 作る順序 | ① **Japanese Action LM** を K151 の実機で完成させる → ② **Japanese Tiny Chat LM** に取り組む |
| 対象の実機 | M5 スタックチャン K151（CoreS3、Flash 16MB、PSRAM 8MB、servo は Feetech SCS0009 ×2） |
| 公開 | モデルは Hugging Face の `ayousanz`、合成データセットは `japanese-data-analyze` で公開する（モデルは公開の前にユーザーの確認を取る。2026-09-29 時点では保留中）。どちらも **CC BY-SA 4.0**（商用利用可）で、Community contributions は off |
| 期限 | 決まっていない。できるだけ早く作る |
| 進め方 | 実装、学習、評価、実機での計測は、すべて Claude Code が実行する。学習と合成データの生成は vast.ai で行う |

既存の小型モデルには、次の4つを同時に満たすものがありません（TinyLM-Bench で確認）。本プロジェクトは、この空白を埋めることを狙います。

- 日本語を理解できる
- ESP32 に載る大きさである
- 厳密な Action を出力できる
- 安全に no-action を返せる

## 作るもの

| 成果物 | 内容 | 公開先とライセンス |
|---|---|---|
| **Japanese Action LM** | 日本語の命令 → Action の JSON（0〜2個、`[]` が no-action）。Action は `look` / `set_expression` / `nod` の3種類。**3M（3.15M parameter）INT4 に決定**。配布ファイル（`.jtlm`）は約 2.0MB（tokenizer の 0.27MB を含む） | Hugging Face、CC BY-SA 4.0 |
| **合成データセット** | Action LM の学習データ。オープンモデルで生成する | [Hugging Face](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)、**public、manual gate**、CC BY-SA 4.0（2026-09-29 公開） |
| **ESP32 用の推論 runtime** | K151 の上で動かし、Action を servo の動きに変える。C の runtime（`runtime/host/`）と firmware（`firmware/jtalm_action/`）は動作済みで、servo を動かす部分はこれから | GitHub（本リポジトリ。現在は private で、公開の時期は Phase 7 で判断）、Apache-2.0 |
| **Japanese Tiny Chat LM** | 短い日本語の応答。実機の候補は 10M（20M は PC での品質比較）。Action LM の完成後に作る | Hugging Face、CC BY-SA 4.0 |

出力の例:

```text
右を向いて、ちょっと嬉しそうにして
→ [{"name":"look","arguments":{"direction":"right","amount":"normal"}},
   {"name":"set_expression","arguments":{"expression":"happy"}}]

右を向かないで
→ []
```

開発者向けの追加の公開物（ESP-IDF の component、tool を追加するための fine-tuning の手順）は、モデルが完成してから判断します。

### Action LM の完了条件

- 完全一致 90%以上、否定と multi-action それぞれ 90%以上、no-action の recall 95%以上と precision 0.90以上、schema 妥当 100%
- 既存の小型モデル（Needle 2、FunctionGemma 270M、MimiModel）に、厳格一致率で勝つ
- M3 の評価セット（1,189件）で、ルールベースの baseline（完全一致 76.4%）を、全体とカテゴリ別の両方で上回る
- 量子化後も精度を保ち、host の C 実装と一致し、K151 の実機で容量、速度、安定性の基準を満たし、servo を実際に動かす

目標値は M4 の最初の評価の後に見直し、据え置きました（no-action の precision を追加）。2026-09-29 時点で、servo を実際に動かすこと以外はすべて満たしました（3M INT4 で評価セットの完全一致 94.3%、実機でも同じ出力）。詳しくは [`docs/README.md`](docs/README.md) §1 と [`docs/roadmap.md`](docs/roadmap.md) を参照してください。

## 学習データの方針

- **正解ラベルは、schema の組み合わせからプログラムで先に決め（label-first）、その意味の文章を Apache-2.0 / MIT のオープンモデル**に vast.ai 上で書かせる。モデルが文を JSON に変換し直して正解と一致した文だけを残す。学習データ（v0.4、47,450件）は7つの書き手（Qwen3、calm3-22b、sarashina2.2-3b、ABEJA-Qwen2.5-32b-Japanese、Mistral-Nemo-Japanese、granite-3.3-8b、ELYZA-Shortcut-Qwen-32B）が書き、評価セットは別のモデル（llm-jp-3.1-13b-instruct4）と別の prompt で作る。量より書き手の多様さが効いた（3M で 84.4% → 91.7% → 94.3%）。
- no-action の負例には、ライセンスが両立する既存の人手データ（MASSIVE の日本語など）を使う。
- **Claude Code は、生成・検査・分割のコードを作って実行するだけ**で、学習データの文章やラベルは書かない。Codex（ChatGPT のプラン）もデータの中身には使わない。どちらも、利用規約で出力を学習に使うことに制限があるため。
- すべてのデータの出典とライセンスを manifest に記録する。

詳しくは [`docs/data.md`](docs/data.md) を参照してください。

## 進捗と次の作業

| 項目 | 状態 |
|---|---|
| Private repository、LICENSE、設計文書 | 完了 |
| 実機（K151）の初回調査と Flash のバックアップ（B0） | 完了 |
| 既存モデルの検証（TinyLM-Bench）と計画への反映 | 完了 |
| ゴール、ライセンス、学習データの方針の決定 | 完了（2026-09-29） |
| vast.ai の API key（`.env`） | 設定済み。認証を確認済み |
| Hugging Face の token（`.env` の `HF_TOKEN`） | 設定済み。user `ayousanz` の token で、`japanese-data-analyze` への write 権限も確認済み |
| M1 リポジトリ基盤（uv、Python 3.13、`uv.lock`、pytest、ruff） | 完了 |
| M2 Action schema v0 と評価の土台（validator、角度への変換、評価指標。TinyLM-Bench の結果を再現） | 完了 |
| M2.5 vast.ai の実行基盤（GPU での torch と vLLM の動作確認、自動削除、費用の記録） | 完了 |
| M3 合成データセット（学習 9,067 件 + validation 477 件、評価 1,189 件、ルールベースの baseline 76.4%） | 完了。[Hugging Face で公開](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)（public、manual gate） |
| M4 Tokenizer（SentencePiece 2k）と 3M / 5M / 20M の学習 | 完了。評価セットの完全一致は 3M が 84.4%、20M が 83.9%（ルールベースは 76.4%）。single、correction、英語はまだ届かない |
| M5（grammar、confidence gate、量子化） | 完了。grammar で致命的な誤りを減らし、INT4 でも精度は落ちない。confidence gate（閾値 0.970）は実機で標準で有効（致命的な誤り 2.0% → 0.6%） |
| データ v0.3 / v0.4 | 完了。書き手を 1 → 3 → 7 に増やし、v0.4 は学習 47,450件（v0.4 はローカルのみで、公開していない） |
| M6 Host C runtime | 完了。PyTorch と出力が完全に一致（3M INT4 + grammar で評価セットの完全一致 94.3%） |
| Track B（B0〜B3、B2.5：ESP-IDF の環境、評価用 firmware、既存 runtime の実機速度） | 完了。esp32-llm の stories3M INT8 は約 7 tok/s |
| B2 servo の座標の確認 | 完了（2026-09-29、ユーザーの立ち会いで実施）。中立は yaw 460 / pitch 620、ロボット自身の右へ回すと yaw の raw が減る |
| A1〜A3 実機での動作（動作の変換、表情、servo） | 完了（2026-09-30、ユーザーの立ち会いのもとで確認） |
| B4 実機への移植と計測 | 完了。評価セット全 1,189件で実機の出力が host と一致。3M INT4 は1回の応答の中央値 1.08〜1.15 秒 → **モデルサイズは 3M INT4 に決定** |

次の作業は、次の順序で進めます。各マイルストーンの目的と完了条件は [`docs/roadmap.md`](docs/roadmap.md) §12 にあります。

1. ~~**M1:** uv によるリポジトリ基盤~~（完了）
2. ~~**M2:** Action schema v0 と評価の土台~~（完了）
3. ~~**M2.5:** vast.ai の実行基盤~~（完了）
4. ~~**M3:** 合成データセットの作成と Hugging Face への公開~~（完了）
5. ~~**M4:** Tokenizer と 3M / 5M / 20M の学習~~（完了。結果は [`docs/roadmap.md`](docs/roadmap.md) §12「M4 の結果」）
6. ~~**M5:** grammar と量子化~~（完了。INT4 でも精度は落ちない）
7. ~~**データ v0.3:** 書き手を3つに~~（完了。3M で 91〜92%）
8. ~~**M6:** Host C runtime~~（完了。PyTorch と出力が完全に一致）
9. ~~**データ v0.4:** 書き手を7つにして約 5 万件~~（完了。3M で 94.2〜94.4%、Action の目標値をすべて満たした。データは v0.4 を採用）
10. ~~**B4:** 実機への移植と速度の計測~~（完了。実機の出力は host と一致し、3M INT4 は応答の中央値 1.15 秒）→ **モデルサイズは 3M（INT4）に決定**
11. ~~**servo の確認（B2）**~~（完了。中立は yaw 460 / pitch 620、右へ回すと yaw の raw が減る）
12. ~~**A1〜A3:** 動作の変換（dispatcher）、表情の表示、servo の driver~~（完了。servo は dry-run で確認済み。画面ありの応答は中央値 1.23 秒）
13. ~~**人が書いた文の評価セット**~~（完了。1,159件で完全一致 98.4%、誤って動くのは 1.1%）
14. ~~**実機で首を実際に動かす確認**~~（完了。LM の出力で首と表情が動き、否定や雑談では動かないことを確認。うなずきは 14° に調整）
15. ~~**データ v0.5 / v0.5.1 と評価セット v2（12パターン）**~~（完了。実行できない依頼で誤って動く割合 18.2% → 0.3%、人が書いた文で誤って動く割合 1.1% → 0.0%。実機の標準を v0.5.1 の 3M に置き換えた）
16. モデルの公開（`ayousanz`）は、**ユーザーの判断で保留中**。公開するときは、直前に内容を提示して確認する
17. Action の完了後、Japanese Tiny Chat LM（10M。事前学習の corpus の決定から）

> [!IMPORTANT]
> 2026-09-29 時点で、LM の精度（PC 上と実機の一致）、量子化後の精度、実機での速度とメモリーは測定済みです。servo の向きと中立の位置も実機で確認しました（B2）。画面や servo と同居させたときのメモリー、電力、Action から servo を実際に動かす確認はまだです。文書中の「目標値」「実測値」「確認済み事実」を区別してください。

## 構成

共通の日本語 Tokenizer、学習基盤、量子化形式、ESP32-S3 推論 Runtime を共有し、Action LM と Chat LM を別々の checkpoint として開発します。十分な性能が得られた後に、`<chat>` / `<action>` モードを持つ Unified Model を実験します。

設計の要点:

1. 対象は画像を入力しないため VLA ではなく、**Tiny LM + Language-to-Action / Tool-Calling LM** である。
2. 本計画の範囲は **LLM を作ること**に限る。LM は、Flash 1.5〜5MB と PSRAM workspace 4MB 以下という LM 用の予算を前提に開発する。音声認識、音声合成との同居と統合は範囲外とする。
3. Action の出力は、TinyLM-Bench と同じ形式の action call の配列にする。方向と量はカテゴリで出力し、角度への変換は firmware 側で行う（yaw は正の値が右）。
4. grammar-constrained decoding、confidence gate、実行側の validation の3段で、出力を制約する。
5. 既存の小型モデルがすべて失敗した **multi-action、否定、no-action** を重点的に学習する。
6. 最初の1周は、3M / 5M の **Action 専用のスクラッチ学習**で行う。原因を切り分けるために、実機には載せない上限参照として 20M も学習する（学習は vast.ai）。
7. 実機の build は ESP-IDF v5.5.5（Docker image）に固定する。

## 文書

- [`docs/README.md`](docs/README.md): プロジェクト全体像、ゴール、決定事項の記録、文書索引
- [`docs/architecture.md`](docs/architecture.md): モデル、Runtime、Action schema、メモリ設計、公開構成案
- [`docs/data.md`](docs/data.md): 学習データの方針、規約の調査結果、使うデータと生成モデル、合成データの公開方法
- [`docs/roadmap.md`](docs/roadmap.md): 開発フェーズ、実装マイルストーン、評価指標、完了条件、工数の見積もり
- [`docs/development.md`](docs/development.md): uv、vast.ai、認証情報、実機操作、ライセンスの運用ルール
- [`docs/hardware.md`](docs/hardware.md): 対象の実機（K151）の構成、実機調査の計測値、Flash のバックアップ
- [`docs/research_notes.md`](docs/research_notes.md): 先行例と既存モデルの検証結果、差別化の仮説
- [`runtime/host/README.md`](runtime/host/README.md): C の推論 runtime（`.jtlm` 形式、build、PyTorch との一致の確認）
- [`firmware/README.md`](firmware/README.md): CoreS3 向けの firmware（build、書き込み、実機での計測）

## 開発環境

- Python（3.13）は **uv** で管理し、依存の追加は `uv add` だけを使う（`uv pip` は使わない）。
- 学習と合成データの生成は **vast.ai** で行う。
- 秘密情報はリポジトリ直下の `.env` に置く（Git の管理外）。

```sh
uv sync --locked --all-groups   # 環境を作る（学習用の torch も入れる場合）
uv run ruff check .             # lint
uv run --group train pytest     # test（model の test には torch が必要）
```

| 変数 | 用途 |
|---|---|
| `VAST_API_KEY` | vast.ai の API key |
| `HF_TOKEN` | Hugging Face の access token（user `ayousanz`。モデルは `ayousanz` に、データセットは `japanese-data-analyze` にアップロードする） |

詳しくは [`docs/development.md`](docs/development.md) を参照してください。

## ライセンスと公開

| 対象 | ライセンス |
|---|---|
| ソースコードと文書（本リポジトリ） | [Apache License 2.0](LICENSE)（Copyright 2026 ayutaz） |
| モデルの重み（Hugging Face） | **CC BY-SA 4.0**（商用利用可。利用時の表示が必要で、改変したモデルも同じライセンスで公開する必要がある） |
| 合成データセット（Hugging Face） | **CC BY-SA 4.0**（public、manual gate） |
| 学習データ | CC BY-SA 4.0 と両立するものだけを使う（[`docs/data.md`](docs/data.md)） |

モデルを公開するのは、データの出典、ライセンス、再現性、実機での評価、安全性の審査をすべて通過し、ユーザーが承認したものだけです（2026-09-29 時点では保留中）。データセットは、出典、ライセンス、再現性、規約の確認を通過して公開しました（2026-09-29）。
