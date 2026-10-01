# 学習データと評価データ

Action LM の学習データと評価データについて、作り方、出典とライセンス、版ごとの違い、公開範囲をまとめます。データを作り直す手順は [`training.md`](training.md) を参照してください。

## 方針

| 項目 | 内容 |
|---|---|
| 正解ラベル | **label-first**。Action schema の組み合わせから、意図（spec）と正解の JSON をプログラムで先に決める（`jtalm.data.specs`、`jtalm.data.focus`） |
| 文章 | spec の意味の日本語の文を、**ライセンスが両立するオープンモデル**（Apache-2.0 / MIT）に書かせる。または、ライセンスが両立する**人が書いたコーパス**から取る |
| 検証 | すべての文を **Qwen3-30B-A3B-Instruct-2507 が温度 0** で Action の JSON に変換し、先に決めた正解と一致した文だけを残す |
| 使わない出力 | 学習・評価データの文章と正解に、Claude や ChatGPT などの出力を使わない。これらのサービスは、出力を AI モデルの学習に使うことを利用規約で制限しているため |
| 重複と漏れ | 正規化した文で重複を除く。評価セットの文は、学習データにも validation にも入れない（下の「評価セットを学習に入れないための仕組み」） |
| 記録 | 出典、ライセンス、生成モデル、prompt の版、件数、落とした理由の内訳、sha256 を manifest（[`datasets/manifests/`](../datasets/manifests/)）に記録する |

重みを CC BY-SA 4.0 で公開するため、使うデータは次の条件を満たすものに限ります。

| 使える | 使えない |
|---|---|
| CC BY-SA、CC BY、CC0、パブリックドメイン、MIT / Apache-2.0 などのデータ | 非営利限定（NC）や改変禁止（ND）のデータ |
| Apache-2.0 / MIT のオープンモデルが書いた文 | 利用規約で学習への利用を制限しているサービスの出力 |
| — | 出典やライセンスが分からないデータ |

使わないモデルの例:

- Gemma 1〜3（出力で学習したモデルも規約の対象になる）
- Llama 系（派生モデルの名前に「Llama」を付ける義務がある）
- Mistral Large（研究用途のみ）

## 書き手と検証役のモデル

| モデル | ライセンス | 役割 | 使った版 |
|---|---|---|---|
| `Qwen/Qwen3-30B-A3B-Instruct-2507`（bf16、61GB） | Apache-2.0 | 学習データを書く。**すべての文の検証役**（温度 0） | v0〜 |
| `llm-jp/llm-jp-3.1-13b-instruct4`（bf16、約27GB） | Apache-2.0 | **評価セットだけ**を書く（v0 eval、eval v2）。学習データは書かない | 評価セット |
| `cyberagent/calm3-22b-chat`（bf16、45GB） | Apache-2.0 | 学習データを書く | v0.3〜 |
| `sbintuitions/sarashina2.2-3b-instruct-v0.1`（bf16、6.7GB） | MIT | 学習データを書く | v0.3〜 |
| `abeja/ABEJA-Qwen2.5-32b-Japanese-v1.0`（bf16、65GB） | Apache-2.0 | 学習データを書く | v0.4〜 |
| `cyberagent/Mistral-Nemo-Japanese-Instruct-2408`（bf16、25GB） | Apache-2.0 | 学習データを書く | v0.4〜 |
| `ibm-granite/granite-3.3-8b-instruct`（bf16、16GB） | Apache-2.0 | 学習データを書く | v0.4 |
| `elyza/ELYZA-Shortcut-1.0-Qwen-32B`（bf16、65GB） | Apache-2.0 | 学習データを書く | v0.4〜 |

- 学習データと評価セットで書き手を分けているので、特定の書き手のくせを覚えただけのモデルは、評価で点が下がります。
- 学習データの検証役は、文を書いたモデルと同じ Qwen3 の場合があります。それでも、温度 0 で「意図した正解と一致する文だけを残す」一貫性の検査として働きます。llm-jp-3.1-13B は雑談や否定の文にも動作を出力することが多く、検証役には使っていません。評価セットは llm-jp が書き、文を書いていない Qwen3 が検証します。

## 人が書いた文の出典

| データ | ライセンス | 使い道 |
|---|---|---|
| [MASSIVE](https://huggingface.co/datasets/AmazonScience/massive)（ja-JP、v1.1） | CC BY 4.0 | train を学習データの負例（`[]`）に、test を v0 eval と human v1 の負例に使う。頭や顔の動作に触れる発話は除く。v0.5 の間違えやすい例の収集にも train を使う |
| [Tatoeba](https://tatoeba.org/en/downloads)（日本語文） | CC BY 2.0 FR | human v1 の正例と否定の依頼。評価用に取り分けた部分の外側を、間違えやすい例の収集に使う |
| [JESC](https://nlp.stanford.edu/projects/jesc/)（映画・ドラマの字幕） | CC BY-SA 4.0 | Tatoeba と同じ |
| [YJ_AmbigDialogue](https://github.com/yahoojapan/YJ_AmbigDialogue)（音声アシスタントへの発話） | CC BY 4.0 | human v1 の負例 |
| [J-CRe3](https://github.com/riken-grp/J-CRe3)（家庭内でロボットに話しかける人の発話） | CC BY-SA 4.0 | human v1 の負例。書き起こし記号（`(F えっと)` など）は取り除く |
| [DSLC3](https://dialog-system-live-competition.github.io/dslc3/data.html)（chatbot との対話ログ） | MIT | human v1 の負例 |

ロボットに首・表情・うなずきを頼む、人が書いた日本語の文をまとめて含む公開データセットは、2026年9月29日の調査では見つかりませんでした。そのため、正例は合成し、人が書いた文は主に評価と負例に使っています。

## 生成と検査の流れ

1. **正解を先に決める:** `jtalm.data.specs` が spec と正解を網羅的に作ります。
   - single: 20 通り
   - multi_action: 順序つきの2動作、126 通り
   - negation: 21 通り（量つきの否定、全般の否定、2つの動作をまとめた否定などを含む）
   - correction: 16 通り（「A ではなく B」と、一部だけを否定する依頼）
   - no_action: 8 つの話題
2. **文を書かせる:** vLLM の OpenAI 互換 API で書き手を動かし、spec の意味の日本語の文を書かせます。出力は JSON に制約します（`response_format`）。prompt では、spec ごとに必ず文に入れる要素（量の言葉、うなずく回数、2つの動作の順序、言い直しの形）を指定し、v0.3 からは 15 種類の文体（疑問形の依頼、遠回しな依頼、誘う言い方、呼びかけ、カタカナ語など）から4つを無作為に選びます。評価セットには、否定の有無だけが違う対比ペアと、少量の英語も入れます。
3. **検証する:** Qwen3 が温度 0 で各文を JSON に変換し、正解と一致した文だけを残します（`jtalm.data.generate` の verify phase）。
4. **軽い検査:** 長さ、文字化け、否定との矛盾（肯定の依頼に否定の語がある、否定の依頼に否定の語がない）を調べます。方向や量のキーワードで正解を確かめる検査は**わざと入れていません**。入れると、キーワードの規則で解ける文ばかりが残り、ルールベースの baseline が不当に高い点を取るためです。
5. **重複と漏れを除く:** 重複、学習データと評価セットの重なりを除きます。
6. **分割と記録:** 新しく加えた文は、カテゴリごとに 5% を validation に分けます。前の版のファイルはそのまま残し、評価セットは変えません（`jtalm.data.build --base`）。

## データの版

学習データの件数（train / validation）です。どの版も v0 の評価セット（1,189件、sha256 `24120eb2…`）を共有します。

| 版 | train | validation | 加えたもの | manifest |
|---|---:|---:|---|---|
| v0 | 9,067 | 477 | Qwen3 が書いた文と MASSIVE の負例 | [`action_v0.json`](../datasets/manifests/action_v0.json) |
| v0.3 | 18,071 | 951 | 書き手を3つに（calm3、sarashina2.2、Qwen3） | [`action_v0.3.json`](../datasets/manifests/action_v0.3.json) |
| v0.4 | 47,450 | 2,497 | 書き手を7つに（ABEJA、Mistral-Nemo-JA、granite、ELYZA を追加） | [`action_v0.4.json`](../datasets/manifests/action_v0.4.json) |
| v0.5 | 64,136 | 3,375 | 弱点を狙った文（eval v2 と同じパターン。英語を除く11）と、間違えやすい例 | [`action_v0.5.json`](../datasets/manifests/action_v0.5.json) |
| **v0.5.1**（採用） | **66,809** | **3,515** | 命令形、「下さい」、言い直しの追加 | [`action_v0.5.1.json`](../datasets/manifests/action_v0.5.1.json) |

train のカテゴリ別の件数:

| 版 | single | multi_action | negation | no_action | correction |
|---|---:|---:|---:|---:|---:|
| v0 | 1,566 | 1,995 | 2,204 | 2,218 | 1,084 |
| v0.3 | 4,252 | 4,235 | 3,780 | 4,111 | 1,693 |
| v0.4 | 12,628 | 12,005 | 8,791 | 10,142 | 3,884 |
| v0.5 | 17,495 | 13,231 | 9,502 | 19,717 | 4,191 |
| v0.5.1 | 19,436 | 13,231 | 9,502 | 19,717 | 4,923 |

### v0

- 学習データは Qwen3 が書き、Qwen3 が温度 0 で検証しました（prompt の版 `action-v0.2`）。否定は、最初の生成で割合が足りなかったので、否定の spec だけを追加で生成しました（`configs/action_v0_negation_topup.json`）。
- train の no_action のうち 1,148件（validation は 52件）は MASSIVE ja-JP の train です。negation は 24.3%、no_action は 24.5% です。
- 設定は `configs/action_v0.json` です。

### v0.3

- v0 に、calm3（6,000文）、sarashina2.2（4,000文）、Qwen3（4,000文）が書いた文を加えました（train +9,004、validation +474）。検証を通った割合は Qwen3 73%、calm3 69%、sarashina2.2 62% です。
- 同じ書き手のデータを増やしても精度がほとんど伸びなかったので、量は書き手を増やして稼ぐことにしました（[`evaluation.md`](evaluation.md)）。
- 設定は `configs/action_v03_*.json` です。

### v0.4

- v0.3 に、7つの書き手が書いた文を加えました（train +29,379、validation +1,546）。検証を通った割合は、granite の 48% から ABEJA の 72% まで書き手によって違います。
- negation は 18.5% で、目標の 20% をわずかに下回ります。
- 設定は `configs/action_v04_*.json` です。

### v0.5

- **弱点を狙った文:** eval v2 と同じパターンの spec（`jtalm.data.focus`。英語を除く11パターン）を、学習用の6つの書き手（ABEJA、Mistral-Nemo-JA、ELYZA、calm3、sarashina2.2、Qwen3）が書きました（約 1.85万文）。検証を通った 12,247件（train と validation の合計）を加えました。
- **間違えやすい例:** 下の「間違えやすい例の収集」で集めた 5,317件（train 5,063、validation 254）を、正解 `[]` で加えました。
- 評価セット（human v1、eval v2）の文を除外して組み立てました（`jtalm.data.build --exclude`）。
- 設定は `configs/action_v05_*.json` です。

### v0.5.1（採用）

- v0.5 のモデルに残った誤り（命令形「見ろ」「笑え」の確信度が低い、「下さい」の「下」を方向と読む）を狙って、命令形、「下さい」を漢字で書いた依頼、言い直しの文を ABEJA、calm3、Qwen3 が書きました（train +2,673、validation +140。single +1,941、correction +732）。
- この2つのパターン（`imperative_forms`、`kanji_kudasai`）は学習データだけにあり、評価セットにはありません。
- 設定は `configs/action_v051_*.json` です。

## 評価セット

どの評価セットも、学習にもモデルの選択（確信度の gate（confidence gate）の閾値、checkpoint の選択）にも使いません。閾値と checkpoint は validation で選びます。結果は [`evaluation.md`](evaluation.md) にあります。

### v0 eval（LLM が書いた文）

| 項目 | 内容 |
|---|---|
| 件数 | 1,189件。single 335、multi_action 192、negation 270、no_action 337（うち MASSIVE test 150）、correction 55。英語 35件、対比ペア 80組 |
| 書き手 | llm-jp-3.1-13b-instruct4。prompt で例に挙げる文体も、学習データとは別のもの（`jtalm.data.prompts` の `STYLES_EVAL`）。Qwen3 が温度 0 で検証 |
| ファイル | v0 以降のすべての版で同じファイル（sha256 `24120eb2…`） |

### human v1（人が書いた文）

| 種類 | 出典 | 件数 |
|---|---|---:|
| 正例（依頼） | Tatoeba、JESC | 62 |
| 否定の依頼（`[]`） | Tatoeba、JESC（「こっち見ないで」など） | 9 |
| 負例（`[]`） | YJ_AmbigDialogue 389、J-CRe3 223、DSLC3 294、MASSIVE test 182 | 1,088 |

合計 1,159件（依頼 62件、依頼でない文 1,097件）。記録は [`action_human_v1.json`](../datasets/manifests/action_human_v1.json) です。

- **正例の抜き出し:** 文全体が「呼びかけ + 量 + 動作 +（もう1つの動作）+ 依頼の語尾」だけでできている文を拾い、当てはまった規則から正解を決めます。「彼は笑って答えた」のような文は拾いません（`jtalm.data.human_eval`）。
- **検証:** すべての候補を Qwen3 が温度 0 で JSON に変換し、規則の正解と一致したものだけを残しました。不一致は 19件で、そのうち 18件は「面白い面白い」を笑顔と答えたような感情の文です。
- **重複:** v0.4 の学習データ、validation、v0 eval と重なる文を除きました。
- **限界:** 正例は人に向けた依頼で、件数が少なく、「正面を向く」と「笑う」に偏ります。主な目的は、現実の発話で誤って動かないか（負例）を測ることです。

### eval v2（パターン別）

12 のパターンごとに、正解を先に決めた spec と書き方の指示（例:「こっち」「私の方」を使う、否定を「〜しないで」以外の形にする、ひらがなだけで書く）を用意し、llm-jp-3.1 が書き、Qwen3 が温度 0 で検証しました。合計 2,446件です。v0.4 の学習データ、v0 eval、human v1 と重なる文は除きました。記録は [`action_eval_v2.json`](../datasets/manifests/action_eval_v2.json) です。

| パターン（ファイル名） | 内容 | 件数 |
|---|---|---:|
| `center_phrasing` | 正面を向く言い方（「こっち」「私の方」「前」など） | 223 |
| `amount_words` | 量の表現（「ちょっとだけ」「めいっぱい」など） | 278 |
| `numbers` | 数字（数字で書いたうなずく回数と、数字を含む雑談や質問） | 167 |
| `negation_forms` | 否定の形（「〜しないで」以外） | 168 |
| `correction` | 言い直し | 44 |
| `order_words` | 2つの動作の順序 | 296 |
| `fragments` | 固有名詞・短い断片（`[]`） | 182 |
| `unexecutable` | 実行できない依頼（方向の語を含む家事の依頼や道順の説明。`[]`） | 286 |
| `orthography` | 表記の揺れ（ひらがなだけ、カタカナ、打ち間違い、方言） | 282 |
| `question_forms` | 疑問形の依頼 | 203 |
| `long_preface` | 前置きのある長い文 | 247 |
| `english` | 英語 | 70 |

## 間違えやすい例の収集（hard-negative mining）

v0.5 で、実際の文で誤って動く例を学習データに加えました（`jtalm.model.mine`）。

1. 人が書いた文の候補を集めます（`jtalm.data.human_eval pool`）。Tatoeba、JESC（25万文を抽出）、MASSIVE の train から、依頼の規則に当てはまらない文を選びます。Tatoeba と JESC は、評価用に取り分けた部分（下）を除きます。合計 456,553文です。
2. v0.4 の 3M モデル（grammar と gate 0.970）に読ませ、動作を出力した 6,353文を候補にします。
3. Qwen3 が温度 0 で変換し、`[]` と一致した 5,317文だけを、正解 `[]` の学習データにします。

## 評価セットを学習に入れないための仕組み

- **評価用の取り分け:** Tatoeba と JESC の文は、human v1 に入った文と、文の hash で決めた約 2割を評価用に取り分け、学習には使いません（`jtalm.data.human_eval.in_eval_pool`）。
- **組み立て時の除外:** `jtalm.data.build --exclude` に評価セットのファイルを渡すと、その文と重なる文を学習データと validation から除きます。v0.5 と v0.5.1 は、human v1 と eval v2 の全ファイルを除外して組み立てました（manifest の `excluded_against`）。
- **既存の版との重複:** `--base` で版を重ねるときは、前の版の train、validation、v0 eval と重なる文を除きます。
- **評価セット同士:** eval v2 は、v0.4 の学習データ、v0 eval、human v1 と重なる文を除いて作りました。

## Hugging Face で公開しているもの

| 対象 | 公開 |
|---|---|
| データ v0 の合成文 | **[`japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth`](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth)**。train 7,919 / validation 425 / test 1,039（合成の文だけ）。public、利用申請制（manual gate）、CC BY-SA 4.0 |
| MASSIVE の行 | 再配布しません。v0 の公開データからも除いています。MASSIVE から取得してください |
| データ v0.3〜v0.5.1 | 公開していません。出典、件数、sha256 は `datasets/manifests/` にあります。[`training.md`](training.md) の手順で作り直せます |
| human v1 | 第三者のコーパスの文なので再配布しません。元のコーパスから作り直せます |
| eval v2 | 公開していません。manifest に件数と sha256 があります |
| モデルの重み | [`ayousanz/JapaneseTinyAgentLM-Action-3M`](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)（CC BY-SA 4.0）。tokenizer も含みます |

データセットの公開は `jtalm.data.publish`（`prepare` と、`--confirm` を付けた `publish`）で行います。公開前に、リポジトリの Community contributions（Discussions と Pull Requests）を off にします。

## 作り直す方法

外部データの取得、vLLM での生成と検証、版ごとの組み立て、評価セットの作り方は、[`training.md`](training.md) にまとめています。

- 学習データも評価セット（v0 eval、human v1、eval v2）も、作り直すには vLLM で Qwen3-30B-A3B-Instruct-2507 などを動かす GPU が要ります。
- Hugging Face のデータセットの test は、v0 eval から MASSIVE の行（150件）を除いた合成の文（1,039件）です。v0 eval と同じファイルではなく、項目名も違います（`input` / `output`。評価の module が読むファイルは `prompt` / `expected`）。
- GPU がなければ、[`results/`](../results/README.md) の結果を確かめることと、公開モデルでの推論（[README](../README.md) の「すぐに試す」）ができます。

生成は seed を固定していますが、再生成した文が元のファイルと同じになる保証はありません。元のファイルとの一致は、manifest の sha256 で確かめられます。

Chat LM の学習データは、まだ決めていません（[`roadmap.md`](roadmap.md)）。
