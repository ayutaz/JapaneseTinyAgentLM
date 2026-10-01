# ロードマップ

本プロジェクトの範囲は、ESP32-S3 単体で動く日本語の小型言語モデル（Action LM と Chat LM）を作り、M5Stack のスタックチャン（K151）で使えるようにすることです。音声認識（ASR）や音声合成（TTS）との統合は、本計画の範囲外です。

## 現状

| 項目 | 状態 |
|---|---|
| Action LM（3M、日本語の発話 → 首・表情・うなずきの Action） | **完成**。評価は [evaluation.md](evaluation.md) |
| 学習データ（v0 → v0.5.1）と評価セット（v0 eval、human v1、eval v2） | 完成。[data.md](data.md) |
| 学習・量子化・書き出しの pipeline | 完成。[training.md](training.md) |
| C runtime（host）と ESP32-S3 firmware | 完成。PC と実機の出力が一致。[architecture.md](architecture.md)、[hardware.md](hardware.md)、[firmware/README.md](../firmware/README.md) |
| Action から servo を動かす dispatcher | 完成（可動域の制限、停止、watchdog を含む）。実機で動作を確認済み |
| Chat LM | 未着手（次の段階） |

### 公開しているもの

| 公開先 | 内容 | ライセンス |
|---|---|---|
| [ayousanz/JapaneseTinyAgentLM-Action-3M](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M) | 重み（INT4 と量子化前の fp32、safetensors）、`.jtlm`（INT4、1,971,456 B）、tokenizer、`inference.py`、スタックチャン用のビルド済み firmware image、`stackchan_chat.py`、第三者のライセンス | CC BY-SA 4.0 |
| [japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth) | 合成データ v0（public、manual gate）。v0.3 以降のデータは公開していません | CC BY-SA 4.0 |
| GitHub（本リポジトリ） | 学習・評価のコード、C runtime、firmware、評価結果（[results/](../results/README.md)） | Apache-2.0 |

### 採用モデルの要点

- 3M（d_model 192、7層、GQA 6/2 heads）、データ v0.5.1、INT4 group 64。grammar で出力は常に schema に合い、確信度の gate（confidence gate）0.868 で確信の低い出力を `[]` にします。
- 人が書いた文（1,159件）: 完全一致 99.6%、依頼 91.9%（5 seed の平均は 85.2 ± 6.4%）、誤って動いた割合 0.0%。
- 実機（CoreS3）: 1回の応答は中央値 1,276ms（[`results/v051_action/device/`](../results/v051_action/device/README.md)）。Wi-Fi、NPU、外部モジュールは使いません。

## 次: Chat LM（約 10M）

短い日本語の会話を実機で返すモデルです。Action LM と同じ runtime（`.jtlm`、C runtime、ESP32-S3 firmware）を使います。

| 項目 | 計画 |
|---|---|
| 規模 | 実機の候補は約 10M。20M は PC で品質を比べる上限参照 |
| 対象 | 1〜3 turn の短い会話。応答は短く、句読点や記号が自然。知らないことを作らず、デバイスにできないことをできると言わない |
| 学習 | 日本語の事前学習（Base）のあとに会話の SFT。事前学習の corpus は**未定**です。corpus のライセンスが重みのライセンスに直結するため、CC BY-SA 4.0 と両立するものから選びます |
| corpus の候補 | 事前学習: 日本語版 Wikipedia（CC BY-SA）、llm-jp-corpus v3 の WARP / KAKEN（CC BY 4.0）。SFT: llm-jp/magpie-sft-v1.0、llm-jp/oasst1-21k-ja・oasst2-33k-ja（Apache-2.0）、dolly-15k-ja（CC BY-SA 3.0） |
| tokenizer | 語彙 4k / 8k / 12k / 16k を比べて決めます。Tokenizer 間では token 単位の perplexity を直接比べず、bits per byte で比べます |
| データの方針 | Action LM と同じく、学習データの文章に利用規約で制限された API の出力を使いません（[data.md](data.md)） |

評価:

- 自動: held-out loss / bits per byte、繰り返し・文字化け・未完の文・終わらない生成の率、デバイスの状態や能力を偽る応答の率、不要な記号や絵文字の率
- 人手: relevance、自然さ、一貫性、簡潔さの rubric と、pairwise の比較（評価者間の一致も記録します）
- 実機: 生成長ごとの first-token latency と tok/s、最大生成長での timeout と watchdog

Baseline:

- 規則とテンプレートによる応答
- LLM-jp-3-150M-instruct3（PC のみ。日本語は流暢ですが、約 1.25GB の RSS を使い、指示への追従が不安定でした）
- 英語の小型 Chat（TinyTalk 2 / cardputer-ai。日本語の入力にはすぐに終わるか英語を続けるだけでした）

完了の条件:

- 対象の場面で、規則・テンプレートの baseline より人の評価で優位であること
- LLM-jp-3-150M-instruct3 との差を定量的に示すこと（10M はその約 1/15 の規模）
- 実機で最大生成長まで timeout や watchdog reset がないこと

その後の実験として、Chat と Action を1つのモデルにまとめる（`<chat>` / `<action>` の token、共通の Base と小さな head など）比較を予定しています。Flash の使用量が明確に減り、両方の品質が別々のモデルから大きく落ちない場合だけ採用します。

## 未解決の項目

| 項目 | 内容 |
|---|---|
| 消費電力 | idle、推論中、servo 駆動中の電流と、1回の依頼あたりの energy は未計測です |
| INT8 の KV cache | KV cache は f32 のまま PSRAM に置いています。INT8 化は未実装です |
| tokenizer の縮小 | `.jtlm` のうち tokenizer が 0.27MB を占めます |
| 人が書いた依頼の評価 | 人が書いた依頼は 62件しかなく、正面を向く・笑うに偏っています。95% 区間が広く（85.5〜98.4%）、seed による差も大きいので、件数を増やす必要があります |
| 英語 | 学習データに入れていないので、英語の依頼はほぼ解けません（seed 0 で 5.3%、5 seed の平均 5.8%）。日本語専用です |
| 表記の揺れと言い直し | 表記の揺れ（ひらがなだけ、カタカナ、打ち間違い、方言。完全一致は 5 seed の平均 83.3%）と言い直し（同じく 85.5%）が弱点です |
| 長時間の安定性と温度 | 連続実行は 1,189件（画面なし）と 200件（画面と dispatcher あり）まで確認済みです。それより長い連続実行、chip の温度と clock の低下は未計測です |
| 比較の baseline | 小型の classifier や seq2seq との比較は未実施です（ルールベースとは比較済み） |
| Base + SFT との比較 | Action LM は Action 専用のスクラッチ学習です。日本語の Base から SFT した場合との比較は、Chat LM の Base ができてから行います |
| 未実装の指標 | 同義表現で同じ Action を返す率（paraphrase consistency）は、まだ評価器にありません |
| OTA と recovery | OTA / rollback / recovery の partition を残した構成は未検討です |
| データの公開 | v0.3 以降の学習データと eval v2 を公開するかは未定です |
| 先行例の調査 | 特許、非公開の製品、索引されない国内発表は調べていません（[prior_art.md](prior_art.md)） |
| Action の拡張 | ESP-IDF component としての runtime の切り出しと、tool を追加するための fine-tuning の手順は未整備です |

## 貢献

不具合の報告、評価セットの追加（特に人が書いた依頼の文）、実機での計測結果などを歓迎します。手順は [CONTRIBUTING.md](../CONTRIBUTING.md) を参照してください。実機で servo を動かすときは、首が動くので、指やケーブルを近づけないでください。
