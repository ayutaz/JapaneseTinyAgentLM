# 学習データの方針

最終更新: 2026-09-29

本文書は、学習データの作り方、使ってよいデータとモデル、合成データの公開方法を定めます。ライセンスの全体像は [`development.md`](development.md) §6 を参照してください。

## 1. 決定事項（2026-09-29）

| 項目 | 決定 |
|---|---|
| データの中身（文章と正解ラベル） | 正解ラベルは schema の組み合わせからプログラムで先に決め（label-first）、文章は **Apache-2.0 / MIT のオープンモデル**が書く。または **ライセンスが両立する既存データ**を使う |
| Claude Code の役割 | 生成、検査、重複の除去、分割、manifest の記録を行う**コードを作って実行するだけ**。学習データの文章やラベルは書かない |
| Codex（ChatGPT のプラン） | データの中身の作成には使わない |
| 合成データを生成する場所 | **vast.ai**（GPU instance 上でオープンモデルを動かす） |
| 合成データの公開 | Hugging Face の organization `japanese-data-analyze` に、**public、manual gate**（利用申請を手動で承認する方式）でアップロードする。ライセンスは CC BY-SA 4.0 |

## 2. 規約の調査結果

両社とも利用しているのはサブスクリプション（個人向けの規約）です。以下は一次情報の原文と照合した要点で、法的な助言ではありません。

| | Claude Code（Pro / Max） | Codex（ChatGPT Plus / Pro） | Apache-2.0 / MIT のオープンモデル |
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
| **`Qwen/Qwen3-30B-A3B-Instruct-2507`**（bf16、61GB） | Apache-2.0（確認済み） | **学習データ**の文を書き、温度 0 で検証する。**評価セット**の文を検証する |
| **`llm-jp/llm-jp-3.1-13b-instruct4`**（bf16、約27GB） | Apache-2.0（確認済み） | **評価セット**の文を書く（学習データには書かない） |
| **`cyberagent/calm3-22b-chat`**（bf16、45GB） | Apache-2.0（モデルカードで確認済み。CyberAgent が一から学習した日本語モデル） | **学習データ**の文を書く（v0.3 から） |
| **`sbintuitions/sarashina2.2-3b-instruct-v0.1`**（bf16、6.7GB） | MIT（モデルカードで確認済み。SB Intuitions の日本語モデル） | **学習データ**の文を書く（v0.3 から） |
| **`abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0`**（bf16、65GB） | Apache-2.0（モデルカードで確認済み。Qwen2.5-32B-Instruct に日本語の継続事前学習と追加学習をしたもの） | **学習データ**の文を書く（v0.4 から） |
| **`cyberagent/Mistral-Nemo-Japanese-Instruct-2408`**（bf16、25GB） | Apache-2.0（モデルカードで確認済み） | **学習データ**の文を書く（v0.4 から） |
| **`ibm-granite/granite-3.3-8b-instruct`**（bf16、16GB） | Apache-2.0（モデルカードで確認済み） | **学習データ**の文を書く（v0.4 から） |
| **`elyza/ELYZA-Shortcut-1.0-Qwen-32B`**（bf16、65GB） | Apache-2.0（モデルカードで確認済み） | **学習データ**の文を書く（v0.4 から） |
| gpt-oss-20b / 120b | Apache-2.0（確認済み） | 学習データの生成の予備（v0.4 では使わなかった） |

- 生成元を分けることで、生成のくせを暗記しただけのモデルを評価で見抜けるようにしています。
- 当初は llm-jp-4.1 を評価セット用にする予定でした。しかし llm-jp-4.1 には思考過程を出す（thinking）版しかなく、出力形式の制約と両立させにくいため、同じ llm-jp 系の llm-jp-3.1 の instruct 版に変えました（M3、2026-09-29）。
- Qwen3 は FP8 版ではなく bf16 版を使います。FP8 を扱える GPU が $1.10/h 以下でほとんど借りられず、A100（Ampere）でも確実に動かすためです。
- **学習データの検証役の変更（v0.2）:** 当初は学習データを llm-jp-3.1 で検証する計画でした。しかし1回目の生成（v0.1）で、llm-jp-3.1-13B は雑談や否定の文にもほぼ毎回動作を出力し、検証役として機能しませんでした（no_action の 1,382 件中 1,192 件が不一致）。そこで v0.2 では、学習データも Qwen3 が温度 0 で検証します。書いたモデルと同じですが、「意図した正解と一致する文だけを残す」一貫性の検査として働きます。評価セットは、これまでどおり llm-jp が書き、文を書いていない Qwen3 が検証します。

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
| [AmazonScience/massive](https://huggingface.co/datasets/AmazonScience/massive)（ja-JP） | CC BY 4.0（確認済み） | 16,521 件。アラーム、家電、雑談などの依頼を人手で日本語化したもの。tool の範囲外の依頼の負例。v0 で使用（頭や顔の動作に触れる19件を除いた 16,502 件から抽出） |
| [apple/mkqa](https://github.com/apple/ml-mkqa)（ja） | CC BY-SA 3.0 | 質問 1万件（人手翻訳） |
| [AmazonScience/mintaka](https://github.com/amazon-science/mintaka)（ja） | CC BY 4.0 | 質問 2万件 |
| JCommonsenseQA、JSQuAD | CC BY-SA 4.0 | 人手で作った質問文 |
| [mainlp/xsid](https://github.com/mainlp/xsid)（ja）、[OHF-Voice/intents](https://github.com/OHF-Voice/intents)（ja） | CC BY-SA 4.0 / CC BY 4.0 | 家電操作などの命令。評価にも使う |

使わないもの: Japanese Daily Dialogue（NC-ND）、NTT の JEmpatheticDialogues / JPersonaChat（評価目的に限定）、出典が不明な function calling の翻訳データ。

### Chat LM（Action の完成後）

- 事前学習: 日本語版 Wikipedia（CC BY-SA）、llm-jp-corpus v3 の WARP / KAKEN（CC BY 4.0）
- SFT: [llm-jp/magpie-sft-v1.0](https://huggingface.co/datasets/llm-jp/magpie-sft-v1.0)（Apache-2.0、確認済み）、llm-jp/oasst1-21k-ja・oasst2-33k-ja（Apache-2.0）、dolly-15k-ja（CC BY-SA 3.0）

## 5. 生成と検査の流れ

v0 の実装は `src/jtalm/data/`（M3）です。

1. **正解を先に決める（label-first）:** `jtalm.data.specs` が、意図（spec）とその正解の JSON をプログラムで網羅的に決める。
   - single: 20 通り
   - multi_action: 順序つきの2動作、126 通り
   - negation: 9 通り（本生成）。追加生成で 21 通りに増やした（下の 7.）
   - correction: 16 通り（「A ではなく B」と、一部だけを否定する依頼）
   - no_action: 8 つの話題
2. **文を書かせる:** vast.ai の GPU instance で、vLLM（v0.30.0）を使って §3 のモデルを動かし、spec の意味の日本語の文を書かせる。出力は JSON に制約する（`response_format`）。
   - 学習データは Qwen3 が書く。
   - 評価セットは llm-jp が、別の言い方の指示で書く。評価セットには、否定の有無だけが違う対比ペアと、少量の英語も含める。
3. **検証する:** 各文を、温度 0 で Action の JSON へ変換させ、1. の正解と一致した文だけを残す。
   - 評価セットは、文を書いていない Qwen3 が検証する。
   - 学習データは Qwen3 が検証する（v0.2。理由は §3）。
   - モデルは1つずつ GPU に載せる（`jtalm.data.generate` の4段階）。
   - 生成の指示（prompt の版 action-v0.2）では、spec ごとに必ず文に入れる要素を指定する。量の言葉（少し、大きく）、うなずく回数、2つの動作の順序、言い直しの形（「〜じゃなくて〜」など）が対象。v0.1 では、これが抜けた文が多かった。
4. **軽い検査:**
   - 長さ、文字化け、否定との矛盾（肯定の命令に否定の語がある、否定の依頼に否定の語がない）を検査する。
   - 重複と、学習データと評価セットの重なりを除く。
   - 方向や量のキーワードで正解を確かめる検査は、**わざと入れない**。入れると、キーワードの規則で解ける文ばかりが残り、ルールベースの baseline が不当に高い点を取るため。
5. **MASSIVE の負例を加える:** 学習には train、評価には test を使い、両者が重ならないようにする。
6. **分割と記録:** 学習データの 5% を検証（validation）に分ける。出典、ライセンス、生成モデル、prompt の版、件数、hash、ルールベースの baseline の評価結果を、manifest（`datasets/manifests/action_v0.json`）に記録する。
7. **否定の追加生成:** v0.2 の1回目の生成では、negation が 15.4% で目標（20%以上）に届かなかった。否定の spec を 9 → 21 に増やし（量つきの否定、全般の否定、2つの動作をまとめた否定など）、否定だけを追加で生成した（`configs/action_v0_negation_topup.json`）。`build` は複数回の生成をまとめて扱う。

実行のコマンド:

```sh
uv run python -m jtalm.infra.job gen_action_v0 --approve-dph 1.10            # 生成と検証（vast.ai）
uv run python -m jtalm.infra.job gen_action_v0_negation --approve-dph 1.10   # 否定の追加生成
uv run python -m jtalm.data.build --raw <run1>/artifacts/raw <run2>/artifacts/raw \
    --extra-config configs/action_v0_negation_topup.json                     # 組み立てと manifest
uv run python -m jtalm.data.publish prepare                                  # 公開用のファイルとカード
uv run python -m jtalm.data.publish publish --confirm                        # 公開（最終確認のあと）

# v0.3 / v0.4: 学習データだけを追加する（前の版のファイルと評価セットはそのまま残す）
uv run python -m jtalm.infra.job gen_action_v03 --approve-dph 1.10
uv run python -m jtalm.data.build --base datasets/action/v0 --raw <run>/artifacts/raw_<writer> ...     --config configs/action_v03_qwen.json --extra-config configs/action_v03_<writer>.json ...     --out datasets/action/v0.3 --manifest datasets/manifests/action_v0.3.json
uv run python -m jtalm.infra.job gen_action_v04 --approve-dph 1.10
uv run python -m jtalm.infra.job gen_action_v04b --approve-dph 1.35   # 失敗した書き手の生成と全体の検証
uv run python -m jtalm.data.build --base datasets/action/v0.3 --raw <run>/artifacts/raw04_<writer> ...     --config configs/action_v04_qwen.json --extra-config configs/action_v04_<writer>.json ...     --out datasets/action/v0.4 --manifest datasets/manifests/action_v0.4.json
```

件数と baseline は [`roadmap.md`](roadmap.md) §12 の「M3 の結果」にあります。

### Tokenizer の学習に使うデータ（M4）

Action LM v0 の tokenizer は、学習データと validation の入力文と出力に加えて、MASSIVE ja-JP の train の発話（CC BY 4.0）で学習しました。語彙の選定の指標には、ほかのどの工程にも使っていない MASSIVE の dev を使いました。評価セットは使っていません。記録は `datasets/manifests/tokenizer_action_v0.json` です（[`architecture.md`](architecture.md) §4）。

### M4 の結果から分かったデータの課題

- 学習データの正解の 48.8% が `[]`（no_action と negation）で、別の書き手の言い回しの依頼を `[]` と答える誤りが多い（[`roadmap.md`](roadmap.md) §12「M4 の結果」）。
- validation（学習データと同じ Qwen3 が書いた文）では約 99% だが、評価セット（llm-jp が書いた文）では 80〜84% になる。書き手が1つしかないことが原因と考えられる。
- 他のモデルの学習データ量と比べると、v0 の 9千件は、事前学習済みのモデルを追加学習するデータ（Google Mobile Actions 9,650件、SNIPS 13,084件）と同程度で、TinyAgent（4万件）より少ない。本プロジェクトは一から学習するので、より多くの多様な例が要ると考える（2026-09-29 の検討）。

### v0.3（2026-09-29）

v0 のファイルはそのまま残し、学習データだけを追加しました（`jtalm.data.build --base`）。評価セットは v0 と同じファイルです（sha256 `24120eb2…`）。

| 項目 | 内容 |
|---|---|
| 書き手 | calm3-22b（6,000文）、sarashina2.2-3b（4,000文）、Qwen3（4,000文）。検証は Qwen3 が温度 0 で行う |
| 生成の指示（action-v0.3） | 文体を 15 種類に増やし（疑問形の依頼、遠回しな依頼、誘う言い方、呼びかけ、カタカナ語など）、依頼ごとに4つを無作為に選ぶ（`prompts.pick_styles`） |
| 通過率 | Qwen3 73%、calm3 69%、sarashina2.2 62% |
| 件数 | train 18,071（+9,004）、validation 951（+474）。single 4,252、multi_action 4,235、negation 3,780（20.9%）、no_action 4,111（22.7%）、correction 1,693 |
| 正解が `[]` の割合 | 48.8% → 43.7% |
| 生成の費用 | A100 PCIe で 0.311 h、約 $0.31（1回目は host の起動が遅く失敗し、約 $0.37） |
| 記録 | `datasets/manifests/action_v0.3.json`。設定は `configs/action_v03_*.json`、job は `gen_action_v03` |

量の確認（同じ書き手のデータを 50% から 100% に増やしても +1.3 point）と v0.3 の結果（書き手を増やして +7〜8 point）から、量は書き手を増やして稼ぐことにしました。

### v0.4（2026-09-29）

v0.3 に、7つの書き手（新しい4つと、続けて使う3つ）で書いた文を追加しました（`jtalm.data.build --base datasets/action/v0.3`）。評価セットは v0 と同じです。

| 項目 | 内容 |
|---|---|
| 新しい書き手 | `abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0`（Apache-2.0）、`cyberagent/Mistral-Nemo-Japanese-Instruct-2408`（Apache-2.0）、`ibm-granite/granite-3.3-8b-instruct`（Apache-2.0）、`elyza/ELYZA-Shortcut-1.0-Qwen-32B`（Apache-2.0）。いずれもモデルカードでライセンスと chat template を確認済み |
| 続けて使う書き手 | calm3-22b、sarashina2.2-3b、Qwen3（seed を変えて追加） |
| 生成と検証 | 47,920文を生成し、Qwen3 が温度 0 で検証した。通過率は 48%（granite）〜72%（ABEJA） |
| 件数 | train 47,450（+29,379）、validation 2,497。single 12,628、multi_action 12,005、negation 8,791（18.5%）、no_action 10,142（21.4%）、correction 3,884 |
| 正解が `[]` の割合 | 43.7% → 39.9% |
| 規則からの逸脱 | negation が 18.5% で、「20%以上」をわずかに下回った。評価では negation の精度は 94〜96% を保った |
| 生成の費用 | 1回目（A100 PCIe、$1.12）は host の空き disk が 152GB しかなく、3つの書き手が失敗した。成功した4つの出力を回収し、`gen_action_v04b`（A100 SXM4、$0.65）で残りを生成して、全体を検証した |
| 記録 | `datasets/manifests/action_v0.4.json`、設定は `configs/action_v04_*.json` |

## 6. Hugging Face への公開

| 項目 | 内容 |
|---|---|
| 対象 | §5 で作った合成データ（single / multi_action / negation / correction / no_action）とデータセットカード。manifest は GitHub で管理する |
| 公開先 | **[`japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth`](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)**（2026-09-29 公開） |
| 公開設定 | **public、manual gate**（利用申請を手動で承認する）。ログインしていない状態でファイルを取得すると HTTP 401 になることを確認済み。**Community contributions（Discussions と Pull Requests）は off**（2026-09-29 に設定し、Discussions の一覧が HTTP 403 になることを確認済み） |
| 時期 | M3 の完了時（モデルより先） |
| 件数 | train 7,919 / validation 425 / test 1,039（合成の文だけ。**公開しているのは v0 だけ**） |
| v0.3 / v0.4 | 公開していない。ファイルは手元の `datasets/action/v0.3`、`datasets/action/v0.4`（Git の管理外）にあり、出典、件数、hash は `datasets/manifests/action_v0.3.json`、`action_v0.4.json` に記録している。公開するかどうかは、モデルの公開と合わせて判断する |
| ライセンス | **CC BY-SA 4.0**（モデルの重みと同じ。2026-09-29 決定） |
| データセットカード | 生成に使ったモデルとライセンス、生成方法、検査の規則、件数、既知の限界、Claude Code の役割（pipeline のコードの作成だけ） |
| 既存データ | MASSIVE などの第三者データは再配布せず、manifest で出典を参照する |
| 手順 | アップロードの直前に、データセットカードと件数を提示して最終確認を取る。認証には `.env` の `HF_TOKEN` を使う。`japanese-data-analyze` への write 権限が必要。`jtalm.data.publish` は、public にする前に `jtalm.infra.hf.disable_community` で Community を off にし、off になったことを確認する |
