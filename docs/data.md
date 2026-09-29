# 学習データの方針

最終更新: 2026-09-29

本文書は、学習データの作り方、使ってよいデータとモデル、合成データの公開方法を定めます。ライセンスの全体像は [`development.md`](development.md) §6 を参照してください。

## 1. 決定事項（2026-09-29）

| 項目 | 決定 |
|---|---|
| データの中身（文章と正解ラベル） | **Apache-2.0 / MIT のオープンモデル**で生成するか、**ライセンスが両立する既存データ**を使う |
| Claude Code の役割 | 生成、検査、重複の除去、分割、manifest の記録を行う**コードを作って実行するだけ**。学習データの文章やラベルは書かない |
| Codex（ChatGPT のプラン） | データの中身の作成には使わない |
| 合成データを生成する場所 | **vast.ai**（GPU instance 上でオープンモデルを動かす） |
| 合成データの公開 | Hugging Face の organization `japanese-data-analyze` に、**public、manual gate**（利用申請を手動で承認する方式）でアップロードする。ライセンスは CC BY-SA 4.0 |

## 2. 規約の調査結果

両社とも利用しているのはサブスクリプション（個人向けの規約）です。以下は一次情報の原文と照合した要点で、法的な助言ではありません。

| | Claude Code（Pro / Max） | Codex（ChatGPT Plus / Pro） | Apache-2.0 のオープンモデル |
|---|---|---|---|
| 出力を学習に使うこと | **Usage Policy:** "Utilization of inputs and outputs to train an AI model (e.g., "model scraping" or "model distillation") without prior authorization from Anthropic" を禁止。競合するモデルに限定していない | **Terms of Use:** "Use Output to develop models that compete with OpenAI." を禁止。競合の定義はない | 制限なし（gpt-oss の利用ポリシーは法令の遵守のみ） |
| 公式の補足 | ヘルプ記事は「競合しないモデルなら可」としつつ、禁止例に "Using Outputs as training targets for models" を挙げている | Terms of Use は "Automatically or programmatically extract data or Output" も禁止している | — |
| 判定 | Anthropic の書面の許可がなければ使わない | 比較的低リスクだが、「問題なし」とは断定できないので使わない | **使う** |

出典:

- [Anthropic Usage Policy](https://www.anthropic.com/legal/aup)（Effective 2025-09-15）
- [Anthropic Consumer Terms](https://www.anthropic.com/legal/consumer-terms)（Effective 2025-10-08）
- [Can I use my Outputs to train an AI model?](https://support.claude.com/en/articles/12326764-can-i-use-my-outputs-to-train-an-ai-model)（2026-03-16）
- [OpenAI Terms of Use](https://openai.com/policies/terms-of-use/)（Effective 2026-01-01）
- [Using Codex with your ChatGPT plan](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- [gpt-oss USAGE_POLICY](https://github.com/openai/gpt-oss/blob/main/USAGE_POLICY)

Claude が書いた生成用の指示文（prompt）やコードまで問題になる余地は、厳密にはゼロではありません。完全な確実性が必要になった場合は、Anthropic に書面の許可を求めます。

## 3. 合成データの生成に使うモデル

| モデル | ライセンス | 用途 |
|---|---|---|
| Qwen3（例: Qwen3-32B） | Apache-2.0（確認済み） | 正例、言い換え、否定文の生成（第一候補） |
| llm-jp-4.1（8B / 33B など） | Apache-2.0（確認済み） | 日本語の言い換え。評価セットは、学習データとは別系統のこのモデルで作る |
| gpt-oss-20b / 120b | Apache-2.0（確認済み） | 予備 |

使わないモデル:

- Gemma 1〜3:「出力で学習したモデル」も規約の対象に含まれる
- Llama 系: 派生モデル名に「Llama」を付ける義務がある
- Mistral Large（研究用途のみ）
- GPT-4、Claude、Gemini などの API の出力

## 4. 既存データ

### Action LM の正例

Action を呼ぶ日本語のデータで、ライセンス上そのまま使えるものは見つかりませんでした（2026-09-29 調査）。正例は §3 のモデルで合成します。

### Action LM の負例（`[]` を返す入力）

| データ | ライセンス | 内容 |
|---|---|---|
| [AmazonScience/massive](https://huggingface.co/datasets/AmazonScience/massive)（ja-JP） | CC BY 4.0（確認済み） | 16,521 件。アラーム、家電、雑談などの依頼を人手で日本語化したもの。tool の範囲外の依頼の負例 |
| [apple/mkqa](https://github.com/apple/ml-mkqa)（ja） | CC BY-SA 3.0 | 質問 1万件（人手翻訳） |
| [AmazonScience/mintaka](https://github.com/amazon-science/mintaka)（ja） | CC BY 4.0 | 質問 2万件 |
| JCommonsenseQA、JSQuAD | CC BY-SA 4.0 | 人手で作った質問文 |
| [mainlp/xsid](https://github.com/mainlp/xsid)（ja）、[OHF-Voice/intents](https://github.com/OHF-Voice/intents)（ja） | CC BY-SA 4.0 / CC BY 4.0 | 家電操作などの命令。評価にも使う |

使わないもの: Japanese Daily Dialogue（NC-ND）、NTT の JEmpatheticDialogues / JPersonaChat（評価目的に限定）、出典が不明な function calling の翻訳データ。

### Chat LM（Action の完成後）

- 事前学習: 日本語版 Wikipedia（CC BY-SA）、llm-jp-corpus v3 の WARP / KAKEN（CC BY 4.0）
- SFT: [llm-jp/magpie-sft-v1.0](https://huggingface.co/datasets/llm-jp/magpie-sft-v1.0)（Apache-2.0、確認済み）、llm-jp/oasst1-21k-ja・oasst2-33k-ja（Apache-2.0）、dolly-15k-ja（CC BY-SA 3.0）

## 5. 生成と検査の流れ

1. Claude Code が生成 pipeline のコードを作る（prompt、生成の設定、検査の規則）。
2. vast.ai の GPU instance で、vLLM などを使って §3 のモデルを動かし、文章とラベルを生成する。
3. ルールで検査する。
   - Schema の妥当性。
   - 入力文に含まれる方向や量の語と、JSON の値が一致しているか。
   - 否定の語を含む入力は `[]` になっているか。
   - 重複、長すぎる文、文字化けを除く。
4. テンプレート（生成の元になったパターン）単位で、学習・検証・評価に分割する。
5. 出典、ライセンス、生成モデル、prompt の版、件数、hash を manifest（`datasets/manifests/`）に記録する。

評価セットは、学習データとは別のモデル（llm-jp-4.1）と別の prompt で生成し、既存の人手データ（MASSIVE など）と組み合わせます。

## 6. Hugging Face への公開

| 項目 | 内容 |
|---|---|
| 対象 | §5 で作った合成データ（正例、否定、言い換え）と manifest |
| 公開先 | Hugging Face の organization **[`japanese-data-analyze`](https://huggingface.co/japanese-data-analyze)**。repository の名前は M3 で決める |
| 公開設定 | **public、manual gate**（利用申請を手動で承認する） |
| ライセンス | **CC BY-SA 4.0**（モデルの重みと同じ。2026-09-29 決定） |
| データセットカード | 生成に使ったモデルとライセンス、生成方法、検査の規則、件数、既知の限界、Claude Code の役割（pipeline のコードの作成だけ） |
| 既存データ | MASSIVE などの第三者データは再配布せず、manifest で出典を参照する |
| 手順 | アップロードの直前に、データセットカードと件数を提示して最終確認を取る。認証には `.env` の `HF_TOKEN` を使う。`japanese-data-analyze` への write 権限が必要 |
