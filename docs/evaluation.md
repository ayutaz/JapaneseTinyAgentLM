# 評価

Action LM の評価の定義、評価セット、採用モデルの結果、誤差の範囲、ここまでの判断の根拠をまとめます。表の数値はすべて [`results/`](../results/README.md) のファイルから取っており、各表の下に出典のファイルを書いています。

- 採用モデル: 3M（3,148,608 params）、データ v0.5.1、seed 0、INT4（group 64、fp16 scale）、grammar + confidence gate 0.868。モデルの構成は [architecture.md](architecture.md)、データは [data.md](data.md)、再現の手順は [training.md](training.md) を参照してください。
- 公開モデル: [ayousanz/JapaneseTinyAgentLM-Action-3M](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M)

## 指標の定義

実装は `src/jtalm/eval/metrics.py`（1件ごとの判定と集計）、`src/jtalm/model/eval_suite.py`（評価セットをまとめた表）、`src/jtalm/eval/bootstrap.py`（誤差の範囲）です。

| 指標 | 定義 |
|---|---|
| exact（完全一致） | 出力を正規化した Action の列が、正解と順序まで含めて一致した割合。TinyLM-Bench の「厳格一致」と同じ定義。出力がない場合は不正な出力として数える |
| カテゴリ別 exact | single / multi_action / negation / no_action / correction ごとの exact。`en` は英語の入力だけの exact |
| requests exact（依頼の正解率） | 正解が動作を含む入力（single、multi_action、correction）だけの exact |
| false actions（誤って動いた割合） | 正解が `[]` の入力（no_action と negation）のうち、何かの動作を出力した割合 |
| critical errors（致命的な誤り） | 次のどれかを1つ以上含む入力の割合: 不正な出力（JSON か schema に合わない）、同じ呼び出しの重複、誤作動（正解が `[]` なのに動作を出す）、逆方向（`look` で正解と反対の向き） |
| no-action precision / recall | 「`[]` を返すべき入力」を陽性とする。precision は `[]` と答えた入力のうち正解も `[]` だった割合（動作の依頼を誤って止めない度合い）、recall は正解が `[]` の入力のうち `[]` と答えた割合 |
| pair accuracy（対比ペア） | 否定の有無だけが違う組（「右を向いて」と「右を向かないで」など）の、両方に正解した割合 |
| name accuracy / slot accuracy | tool 名の列の一致率と、引数（direction、amount、expression、count）の正解率（`jtalm.eval` の report に出ます） |

評価の条件は固定して結果と一緒に記録します（`comparison.json` の `conditions`）: greedy decoding、prompt 形式 `<s> <act> prompt <out>`、評価セットと tokenizer の sha256、grammar と gate の有無、gate の閾値。

## 評価セット

作り方と出典は [data.md](data.md) の評価セットの節にあります。

| セット | 件数 | 内容 |
|---|---:|---|
| v0 eval（LLM が書いた文） | 1,189 | llm-jp-3.1-13b-instruct4 が書き、Qwen3 が検証した文と MASSIVE の test。single 335、multi_action 192、negation 270、no_action 337、correction 55。英語 35件、対比ペア 80組。学習データとは書き手を分けている |
| human v1（人が書いた文） | 1,159 | Tatoeba、JESC、YJ AmbigDialogue、J-CRe3、DSLC3、MASSIVE から抜き出した文。依頼 62件、否定の依頼 9件、負例 1,088件（`[]` が正解の入力は計 1,097件） |
| eval v2（12パターン） | 2,446 | 弱点を調べるためのパターン別の文。llm-jp-3.1 が書き、Qwen3 が検証した。パターンは下の表 |
| TinyLM-Bench 16件 | 16 | 既存モデルとの比較用（英語 8、日本語 8）。モデルの選定には使っていない |

eval v2 のパターン:

| パターン | 件数 | 内容 |
|---|---:|---|
| amount_words | 278 | 量の表現の言い換え（「ほんの少し」「思い切り」など） |
| center_phrasing | 223 | 正面を向く・顔を上げる依頼の言い方（「こっち」「私の方」「前」など） |
| correction | 44 | 言い直し（「A ではなく B」など） |
| english | 70 | 英語の命令と雑談（学習データにないので参考値） |
| fragments | 182 | 人名、作品名、単語だけなどの短い断片（正解は `[]`） |
| long_preface | 247 | 状況や理由の前置きがある依頼 |
| negation_forms | 168 | 「〜しないで」以外の否定の形（「〜しなくていい」「〜するな」など。正解は `[]`） |
| numbers | 167 | うなずきの回数を数字で書いた依頼と、時刻や日付などの数字を含む雑談（正解は `[]`） |
| order_words | 296 | 2つの動作の順序の言葉（「〜してから」「まず〜、それから〜」など） |
| orthography | 282 | ひらがなだけ、カタカナ多め、打ち間違い、方言 |
| question_forms | 203 | 疑問形の依頼（「〜してくれる？」など） |
| unexecutable | 286 | 方向の語を含むが実行できない依頼（物を取る・運ぶ、道順の説明など。正解は `[]`） |

出典: 件数は [`results/v051_action/suite_3m/suite.md`](../results/v051_action/suite_3m/suite.md)

## Decoding と gate の評価方法

- **Grammar:** Action schema に合う token だけを選べるようにした greedy decoding です。出力は必ず schema に合います（[architecture.md](architecture.md)）。
- **Confidence gate:** 生成した token の確率の最小値（grammar の mask をかける前の確率）が閾値より小さいとき、出力を `[]` に置き換えます。
- **閾値の選び方:** validation だけで選びます。validation の exact が gate なしから 0.5 point 以上下がらない範囲で、最も大きい閾値を取ります（`jtalm.model.evaluate.select_gate`）。評価セットは閾値の選択に使いません。採用モデルでは 0.86808（validation の exact は gate なし 98.2%、gate あり 97.8%）で、firmware の既定値は `CONFIG_JTALM_GATE_PERMILLE=868` です。

## 採用モデルの結果

3M、v0.5.1、seed 0、INT4 + grammar + gate 0.868。

| セット | 件数 | exact | requests exact | false actions | critical |
|---|---:|---:|---:|---:|---:|
| v0 eval（LLM） | 1,189 | 93.8 | 87.8 | 0.5 | 0.3 |
| human v1 | 1,159 | **99.6** | **91.9** | **0.0** | 0.0 |
| v2/amount_words | 278 | 94.6 | 94.6 | — | 0.0 |
| v2/center_phrasing | 223 | 93.7 | 93.7 | — | 0.0 |
| v2/correction | 44 | 84.1 | 84.1 | — | 0.0 |
| v2/english | 70 | 45.7 | 5.3 | 6.2 | 2.9 |
| v2/fragments | 182 | 100.0 | — | 0.0 | 0.0 |
| v2/long_preface | 247 | 90.3 | 90.3 | — | 0.0 |
| v2/negation_forms | 168 | 100.0 | — | 0.0 | 0.0 |
| v2/numbers | 167 | 93.4 | 85.7 | 1.9 | 1.2 |
| v2/order_words | 296 | 95.3 | 95.3 | — | 0.0 |
| v2/orthography | 282 | 82.6 | 80.8 | 0.0 | 0.0 |
| v2/question_forms | 203 | 90.1 | 90.1 | — | 0.0 |
| v2/unexecutable | 286 | 99.7 | — | **0.3** | 0.3 |

出典: [`results/v051_action/suite_3m/suite.md`](../results/v051_action/suite_3m/suite.md)（単位は %。「—」はそのセットに該当する入力がないもの）

- 人が書いた文で誤って動いた件数は 1,097件中 0件、実行できない依頼では 286件中 1件です。
- 弱いところ: 表記の揺れ（ひらがなだけの文など、80.8%）、言い直し（84.1%、44件）。英語の依頼は 5.3% で、**日本語専用**として扱ってください。

v0 eval のカテゴリ別の値（採用したモデル seed 0、INT4。decoding の段階ごと。ルールベースとの比較）:

| model | 全体 | single | multi | negation | no_action | correction | en | no-action P / R | 対比ペア | critical |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ルールベース | 76.4 | 60.9 | 46.9 | 88.1 | 99.1 | 76.4 | 77.1 | 79.8 / 94.2 | 83.8 | 2.9 |
| 3M INT4 | 94.6 | 89.6 | 95.8 | 97.0 | 97.6 | 90.9 | 57.1 | 97.0 / 97.4 | 97.5 | 1.5 |
| 3M INT4 + grammar | 94.6 | 89.6 | 95.8 | 97.0 | 97.6 | 90.9 | 57.1 | 97.0 / 97.4 | 97.5 | 1.3 |
| **3M INT4 + grammar + gate 0.868（採用）** | **93.8** | 86.3 | 92.7 | 100.0 | 99.1 | 80.0 | 57.1 | 91.5 / 99.5 | 98.8 | 0.3 |

出典: [`results/v051_action/adopted_q4/comparison.md`](../results/v051_action/adopted_q4/comparison.md)。gate は確信の低い出力を `[]` にするので、依頼の正解を少し下げる代わりに、誤って動くことと致命的な誤りを減らします。no_action はルールベースと同じ 99.1% で、上回ってはいません。FP32（gate なし、seed 0 / 1）の値は [`results/v051_action/comparison.md`](../results/v051_action/comparison.md) にあります。

ルールベース（`jtalm.eval.rule_baseline`）は、キーワードと否定の規則で Action を決める比較用の実装です。

## 誤差の範囲

同じ設定で seed 0〜4 の5回を学習し、それぞれ INT4 + grammar + gate（閾値は各 seed の validation で選ぶ）で評価しました。

| セット | requests exact: seed 0 [95% 区間] | requests exact: 5 seed の平均 ± SD | false actions: seed 0 | false actions: 5 seed |
|---|---|---|---|---|
| human v1 | 91.9 [85.5, 98.4] | **85.2 ± 6.4** | 0.0 [0.0, 0.0] | 0.0 ± 0.0 |
| v0 eval（LLM） | 87.8 [85.1, 90.4] | 88.1 ± 1.2 | 0.5 [0.0, 1.2] | 0.4 ± 0.2 |
| v2/amount_words | 94.6 [92.1, 97.1] | 94.1 ± 0.6 | — | — |
| v2/center_phrasing | 93.7 [90.6, 96.9] | 92.8 ± 1.8 | — | — |
| v2/correction | 84.1 [72.7, 95.5] | 85.5 ± 3.4 | — | — |
| v2/long_preface | 90.3 [86.6, 93.5] | 91.3 ± 1.1 | — | — |
| v2/numbers | 85.7 [76.2, 93.7] | 84.4 ± 1.3 | 1.9 [0.0, 4.8] | 1.2 ± 0.4 |
| v2/order_words | 95.3 [92.9, 97.6] | 95.8 ± 0.7 | — | — |
| v2/orthography | 80.8 [75.7, 85.5] | 81.5 ± 0.8 | 0.0 [0.0, 0.0] | 0.0 ± 0.0 |
| v2/question_forms | 90.1 [85.7, 94.1] | 91.9 ± 2.9 | — | — |
| v2/unexecutable | — | — | 0.3 [0.0, 1.0] | 0.3 ± 0.3 |

出典: [`results/v051_action/ci_3m.md`](../results/v051_action/ci_3m.md)（seed 0 の bootstrap、2,000回の再標本化、percentile 区間）、[`results/v051_action/seeds_3m.md`](../results/v051_action/seeds_3m.md)（5 seed）。exact 全体の値と、表にないセットも両ファイルにあります。

- v0 eval の exact は、5 seed で **94.0 ± 0.6%** です（seed 0 は 93.8%）。
- 人が書いた依頼は seed ごとに 91.9 / 75.8 / 83.9 / 90.3 / 83.9% と大きく動きます。**採用した seed 0 は、5つの中で人が書いた依頼が最も高い seed です。** 期待できる性能としては、5 seed の平均（85.2%）を引用してください。
- validation の exact は 5 seed とも 98.1〜98.3% でほぼ同じで、validation では seed を選べません。
- bootstrap の区間は評価セットの標本のばらつきだけを表し、学習の seed によるばらつきは含みません。人が書いた依頼は 62件しかないので、区間が広くなります（85.5〜98.4%）。

## ここまでの経緯

### データの版と主な結果

| データ | 学習データ | 主な変更 | v0 eval exact（gate なし、seed 0 / 1） | v0 eval exact（採用の decoding） | 人が書いた依頼 | 人が書いた文の false actions | 実行できない依頼の false actions |
|---|---:|---|---:|---:|---:|---:|---:|
| v0 | 9,067 | 書き手 1（Qwen3） | 84.4 | — | — | — | — |
| v0.3 | 18,071 | 書き手 3、文体を 15 種類に | 91.3 / 92.1 | — | — | — | — |
| v0.4 | 47,450 | 書き手 7 | 94.2 / 94.4 | 94.4 | 88.7 | 1.1 | 18.2 |
| v0.5 | 64,136 | 弱点のパターン別の文、間違えやすい負例 | 96.0 / 94.9 | 94.5 | 83.9 | 0.1 | 0.7 |
| **v0.5.1** | **66,809** | 命令形、「下さい」、言い直しの追加 | 94.7 / 94.7 | 93.8 | **91.9** | **0.0** | **0.3** |

出典: gate なしは [`m4_action_v0`](../results/m4_action_v0/comparison.md)、[`v03_action`](../results/v03_action/comparison.md)、[`v04_action`](../results/v04_action/comparison.md)、[`v05_action`](../results/v05_action/comparison.md)、[`v051_action`](../results/v051_action/comparison.md) の `comparison.md`。採用の decoding（INT4 + grammar + gate、seed 0、閾値は各版の validation で選択: v0.4 は 0.97004、v0.5 は 0.82278、v0.5.1 は 0.86808）は [`suite_v04/suite.md`](../results/suite_v04/suite.md)、[`v05_action/suite_3m/suite.md`](../results/v05_action/suite_3m/suite.md)、[`v051_action/suite_3m/suite.md`](../results/v051_action/suite_3m/suite.md)。human v1 と eval v2 は v0.4 の後に作ったので、それより前の版の値はありません。

- v0.4 のモデルは、実行できない依頼の 18.2% で誤って動きました。v0.5 で、その種の文と、人が書いた大量の文で誤って動いた例（Qwen3 で `[]` と確かめたもの）を学習に加え、ほぼ解消しました。
- v0.5 では人が書いた依頼が下がりました（命令形の確信度が低く gate で止まる、「下さい」を「下」と読む）。v0.5.1 で、その言い方を加えて戻しました。
- v0.4 → v0.5.1 で、paired bootstrap の区間が 0 を含まない差: 量の表現 +12.6pt、正面を向く言い方 +6.7pt、実行できない依頼の false actions −17.8pt、人が書いた文の false actions −1.1pt。人が書いた依頼の +3.2pt は区間が −4.8〜+11.3 で、はっきりしません（[`diff_v04_v051.md`](../results/v051_action/diff_v04_v051.md)）。
- v0.5 → v0.5.1 では、人が書いた依頼が +8.1pt [+1.6, +14.5] 上がり、言い直し（v2、44件）が −9.1pt [−18.2, −2.3] 下がりました（[`diff_v05_v051.md`](../results/v051_action/diff_v05_v051.md)）。実際の利用に最も近い人が書いた文を優先して v0.5.1 を採用しました。

### 判断とその根拠

**データは量より書き手の多様さ。** v0 のデータを 25 / 50 / 100% にして 3M を学習すると（2 seed の平均）、74.6% / 82.6% / 83.9% で、50% から先はほとんど伸びませんでした。書き手を 1 → 3 にした v0.3 では +7〜8 point 伸びました。そこで量は書き手を増やして集めました。出典: [`data_scaling_v0/comparison.md`](../results/data_scaling_v0/comparison.md)、[`v03_action/comparison.md`](../results/v03_action/comparison.md)

**モデルサイズは 3M。** v0 eval の exact（gate なし）:

| データ | 3M | 5M | 20M（PC だけの上限参照） |
|---|---:|---:|---:|
| v0 | 84.4 | 79.6 / 82.0 / 81.3（seed 0 / 1 / 2） | 83.9 |
| v0.3 | 91.3 / 92.1 | 89.8 / 89.4 | 90.7 |
| v0.4 | 94.2 / 94.4 | 93.4 / 93.2 | 95.0 |
| v0.5 | 96.0 / 94.9 | 93.8 | — |

出典: [`m4_action_v0`](../results/m4_action_v0/comparison.md)、[`v03_action`](../results/v03_action/comparison.md)、[`v04_action`](../results/v04_action/comparison.md)、[`v05_action`](../results/v05_action/comparison.md) の `comparison.md`

- 5M はどの版でも 3M を上回らず、20M の差は v0.4 で +0.7 point にとどまりました。v0 で 20M も 3M と同程度だったので、精度不足の原因は capacity ではなくデータだと判断しました。
- 実機では 3M INT4 の1回の応答が中央値 1,153ms、5M INT4 は 1,793ms でした（評価セットの先頭 200件。[`results/b4_device/`](../results/b4_device/)）。

**INT8 / INT4 で精度は落ちない。** 重みだけを group 64、対称、fp16 scale で量子化しました。

| model | FP32 | INT8 | INT4 | 出典 |
|---|---:|---:|---:|---|
| 3M v0（grammar なし） | 84.4 | 84.5 | 84.8 | [`m5_quant_on_m4`](../results/m5_quant_on_m4/comparison.md) |
| 5M v0（grammar なし） | 79.6 | 79.6 | 79.5 | 同上 |
| 3M v0.4 seed 0（grammar あり） | 94.2 | 94.2 | 94.3 | [`v04_quant`](../results/v04_quant/comparison.md) |

3M INT4 の `.jtlm` は 1,971,456 B（tokenizer を含む）です。

**Grammar は精度を変えずに致命的な誤りを減らす。** 3M v0 で exact は 84.4% のまま、critical errors が 2.6% → 0.8% になりました（不正な出力と重複がなくなる）。grammar で防げるのは構造の誤りだけで、tool や引数の選び間違いは防げません。出典: [`m5_grammar_on_m4/comparison.md`](../results/m5_grammar_on_m4/comparison.md)

**Gate は、書き手の違う validation で閾値を選ぶと効く。**

| 条件 | exact | critical | 出典 |
|---|---:|---:|---|
| 3M v0、gate なし → gate あり（validation の書き手は1つ） | 84.4 → 80.7 | 2.6 → 0.4 | [`m5_grammar_on_m4`](../results/m5_grammar_on_m4/comparison.md) |
| 3M v0.4 INT4 + grammar、gate なし → gate 0.970（validation の書き手は7つ） | 94.3 → 94.4 | 2.0 → 0.6 | [`v04_quant`](../results/v04_quant/comparison.md)、[`v04_gate`](../results/v04_gate/comparison.md) |
| 同上、human v1 | 95.6 → 98.4（依頼は 93.5 → 88.7） | 4.1 → 1.0 | [`human_v1`](../results/human_v1/comparison.md) |

- v0 では、モデルが「確信を持って `[]` と答える」形で誤ること、validation が学習データと同じ書き手で閾値がほぼ 1 に選ばれることから、gate は逆効果でした。
- v0.4 では、人が書いた文で誤って動く件数が 1,097件中 47件 → 12件に減り、代わりに依頼の取りこぼしが増えました。誤って首が動くことを最も避けたいので、実機では gate を標準で有効にしています。

## 既存モデルとの比較（TinyLM-Bench の16件）

既存の小型モデルは、別に行った検証（TinyLM-Bench、Windows host）で得た16件の出力しか手元になく、1,189件の評価セットでは比べていません。出力は [`tests/fixtures/tinylm_bench/`](../tests/fixtures/tinylm_bench/) にあり、本プロジェクトの評価器でベンチの厳格一致（3 / 6 / 1 件）を再現できることを確かめています。

| model | 規模 | exact（16件） | 出典 |
|---|---:|---:|---|
| Needle 2 | 45M | 18.8 | [`v051_action/comparison.md`](../results/v051_action/comparison.md) |
| FunctionGemma 270M | 270M | 37.5 | 同上 |
| MimiModel（Needle 2 と同じ重み、別の runtime） | 45M | 6.2 | 同上 |
| 3M v0.4 INT4 + grammar | 3.15M | 87.5 | [`v04_quant/comparison.md`](../results/v04_quant/comparison.md) |
| 3M v0.4 INT4 + grammar + gate 0.970 | 3.15M | 75.0 | [`v04_gate/comparison.md`](../results/v04_gate/comparison.md) |
| 3M v0.5.1 INT4 + grammar | 3.15M | 75.0 | [`v051_action/adopted_q4/comparison.md`](../results/v051_action/adopted_q4/comparison.md) |
| **3M v0.5.1 INT4 + grammar + gate 0.868（採用）** | 3.15M | **62.5** | 同上 |
| ルールベース（参考） | — | 100.0 | 同上 |

読むときの注意:

- 16件のうち 8件は英語で、本モデルは英語を学習していません。件数が少なく、統計的な結論には足りません。
- 既存の3モデルは英語の汎用 tool calling のモデルで、本モデルは schema を固定した日本語の Action 専用です。この比較は、**既存モデルがこの日本語の Action の課題をそのままでは解けない**ことを示すもので、「tool calling の能力で上回った」ことを示すものではありません。
- ルールベースが 100% なのは、規則を作るときにこの16件を参照したためです。
- gate をかけると、英語の依頼などの確信の低い出力が `[]` になるので、16件では下がります（75.0% → 62.5%）。
- 規模の比較は「ESP32 で動く Needle 2（45M）の約 1/15」と書けますが、「最小の tool calling のモデル」とは書けません。先行例と主張できる範囲は [prior_art.md](prior_art.md) にまとめています。

## 実機と PC の一致

| 確認 | 対象 | 結果 | 出典 |
|---|---|---|---|
| C runtime（host）と PyTorch | 3M / 5M × FP32 / INT8 / INT4、grammar なし / あり、v0 eval 1,189件 | token 列と出力がすべて一致。exact も同じ（3M INT4 で 84.78%） | [`results/m6_parity/`](../results/m6_parity/) |
| C の tokenizer と SentencePiece | 学習 9,067、validation 477、評価 1,189、無作為 20,000件 | すべて一致 | [`results/m6_parity/3m/parity.json`](../results/m6_parity/3m/parity.json) |
| 実機（ESP32-S3）と host | M4 の 3M FP32 / INT8 / INT4、5M INT8 / INT4、先頭 200件 | 200 / 200 一致 | [`results/b4_device/`](../results/b4_device/) |
| 実機と host（gate を含む） | v0.4 の 3M INT4、v0 eval 全 1,189件 | gate の前と後の出力とも 1,189 / 1,189 一致 | [`results/b4_device/v04_3m_q4_g64_all.summary.json`](../results/b4_device/v04_3m_q4_g64_all.summary.json) |
| 実機と Python（採用モデル） | v0.5.1 の 3M INT4、gate 0.868、先頭 300件 | gate の前と後の出力とも 300 / 300 一致 | [hardware.md](hardware.md) |

実機の出力は PC と一致するので、上の評価結果はそのまま実機の値になります。採用モデルの実機での応答時間は中央値 1,276ms、p90 1,860ms です（decode 約 105 ms/token、prefill 約 46 ms/token）。速度とメモリの詳細は [hardware.md](hardware.md) にあります。

## 再現の方法

学習データ、評価セット、tokenizer、checkpoint の作り方は [training.md](training.md) にあります。評価セットのうち、v0 eval の合成の文は [Hugging Face のデータセット](https://huggingface.co/datasets/japanese-data-analyze/JapaneseTinyAgentLM-Action-Synth) の test にあります。human v1 と eval v2 は配布していないので、[data.md](data.md) の手順で作ってください。

全評価セットの表（gate の閾値は `--val` で選びます）:

```sh
uv run --group train python -m jtalm.model.eval_suite \
    --ckpt <checkpoint のディレクトリ>/best_q4_g64.pt \
    --tokenizer tokenizer/out/action_v0_sp2048.model \
    --val datasets/action/v0.5.1/val.jsonl \
    --out runs/local/suite_v051_3m_q4
```

このコマンドで `runs/local/suite_v051_3m_q4/` に `suite.md`、`suite.json`、セットごとの予測（`*_predictions.jsonl`）を作ります。

カテゴリ別の表と TinyLM-Bench の16件:

```sh
uv run --group train python -m jtalm.model.evaluate \
    --ckpt <checkpoint のディレクトリ>/best.pt \
    --tokenizer tokenizer/out/action_v0_sp2048.model \
    --modes plain grammar gate --val datasets/action/v0.5.1/val.jsonl \
    --out runs/local/eval_v051
```

誤差の範囲（入力は `eval_suite` の出力ディレクトリ）:

```sh
uv run python -m jtalm.eval.bootstrap ci runs/local/suite_v051_3m_q4              # 95% 区間
uv run python -m jtalm.eval.bootstrap diff <A の suite> <B の suite>               # paired bootstrap（B − A）
uv run python -m jtalm.eval.bootstrap seeds <seed 0 の suite> <seed 1 の suite> ...  # seed の平均 ± SD
```

実機での一致の確認は `firmware/tools/lm_serial.py`（`--port <PORT>`、例: Windows は COM3、Linux は /dev/ttyACM0）で行います。手順は [firmware/README.md](../firmware/README.md) を参照してください。
