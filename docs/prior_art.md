# 先行例と主張の範囲

マイコン上の小型言語モデルと、スタックチャンの言語モデル連携について、公開されている先行例をまとめます。あわせて、このプロジェクトが何を主張でき、何を主張できないかと、その書き方を定めます。

性能の数値は、board、clock、PSRAM の方式（Octal / Quad）、context、prompt、量子化、計測方法がそれぞれ違います。横に並べて順位を付ける用途には使わないでください。

## マイコン上の言語モデル

### Needle 2 ESP32

一次ソースで確認した事項です。

- 45M parameter の tool calling 用の言語モデルを、ESP32-S3（16MB Flash、8MB Octal PSRAM の特定の board）で動かす。
- モデルは Flash から memory-map する。README の記載はモデル単体で約 13.1MB、download は 13.7MB。
- 240MHz で 534 ms/token（約 1.87 tok/s）。KV cache は約 3.5MB。context は 256 token。
- JSON schema から byte 単位の grammar を作り、schema に合う tool call だけを出す。出力は tool call か空の call で、chatbot ではない。
- ESP32 版の schema 対応には、nested object / array などの制限がある。

このプロジェクトとの関係:

- マイコン上で grammar で制約した tool calling が成り立つことを示している。
- 13MB 級のモデルは、CoreS3 で画面や servo と同居させるには大きい。
- 対象 board は Octal PSRAM、CoreS3 は Quad PSRAM で、PSRAM の帯域が違う。tok/s を直接比べないでください。
- schema を prompt に入れる方式なので、tool を増やすほど context を消費する。

### slvDev/esp32-ai

- 28.9M の stored parameter のうち 25M を Flash 上の lookup table（Per-Layer Embeddings）に置き、token ごとに必要な行だけを読む。4-bit の artifact は 14.9MB。
- ESP32-S3（512KB SRAM、8MB PSRAM、16MB Flash）で 9.88 tok/s と記載。
- TinyStories 用で、質問応答、指示への追従、事実知識は目的としていない。

parameter 数だけでは、能力も常駐メモリも判断できないことを示す例です。PLE は日本語の embedding の肥大化への対策の候補になりえますが、このプロジェクトでは採用していません。

### esp32-mind

- XIAO ESP32-S3 向けの小型言語モデル。esp32-ai を基に、8MB board 向けの target と USB での入出力を加えたもの。4-bit の PLE runtime と、学習・量子化・書き出しのコードを含む。
- 記載された実機例は 40 token / 2.81 秒（14.22 tok/s）。モデルの配置と作業領域の確保の後、PSRAM の空きは約 5,294KiB。
- `xiao-model-v1` は 11,509,632 parameter、int4（group 128）、書き出し後 5,969,116 B（私たちが PC 上で確認した値）。

### doryiii/esp32-llm

llama2.c 系の小型モデルを ESP32 で動かす実験です。

| モデル | Parameter 数 | 形式 | Size |
|---|---:|---|---:|
| stories260K | 260,032 | FP32 | 1,056,540 B |
| stories3M | 3,148,224 | INT8（group 64） | 3,352,576 B |

- 上流の記載は約 12 tok/s（Octal PSRAM の board）。CoreS3（Quad PSRAM）で stories3M INT8 を動かすと、forward だけで 6.5〜7.1 tok/s でした。
- 規模と量子化がこのプロジェクトの 3M に近いので、CoreS3 での速度の基準に使いました。再現手順は [`../firmware/baselines/README.md`](../firmware/baselines/README.md) にあります。

## スタックチャンの firmware

### m5stack/StackChan（K151 の公式 firmware）

- M5Stack のスタックチャン（K151）の firmware、app、server をまとめた公式のリポジトリ。`firmware/` は ESP-IDF v5.5.4 系で、MIT License。
- servo は Feetech の driver（`FTServo_Arduino`）の `SCSCL` で動かす。UART1、1Mbps、TX `G6` / RX `G7`。yaw は ID 1（±128°）、pitch は ID 2（3°〜87°）。
- Motion API の規約は、yaw の正の値が右、pitch は値が大きいほど上。このプロジェクトの Action の座標の規約は、これに合わせています。

### stackchan-idf

- ESP-IDF 5.5 系、C++20 のスタックチャンの firmware（BSL-1.0）。README では 5.5.5 で検証しており、CI も `espressif/idf:v5.5.5` に固定している。
- K151 の胴体に対応している。PY32 IO expander（`0x6F`）の pin 0 で servo の電源を入れ、200ms 待ってから bus を使う。私たちの K151 では servo が ping に答えるまで約 0.85 秒かかったので、本プロジェクトの firmware は固定の時間を待たず、両方の servo が ping に答えるまで最大 3 秒待つ（[`hardware.md`](hardware.md) の「Servo」）。
- `components/scs_servo/` に SCS0009 の driver と台形速度の path generator がある。

このプロジェクトでは、servo の向きと中立位置の確認に使いました。firmware は、stackchan-idf の checkout にある M5Unified / M5GFX（MIT）を使って build します（[`hardware.md`](hardware.md)）。

## 既存の小型モデルとの比較（TinyLM-Bench の16件）

TinyLM-Bench は、作者が本プロジェクトとは別に行った、既存の小型モデルの16件の比較です（非公開。ケースと各モデルの出力は [`../tests/fixtures/tinylm_bench/`](../tests/fixtures/tinylm_bench/) にあります）。16件は英語 8件・日本語 8件で、tool は `look(direction, amount)`、`set_expression(expression)`、`nod(count)` の3種類です（Action schema v0 はこの形式に合わせています。[`architecture.md`](architecture.md)）。厳格一致は FunctionGemma 270M が 6/16、Needle 2 が 3/16（日本語は 1/8）、MimiModel が 1/16 で、3モデルとも multi-action と否定のケースを1件も正解しませんでした。採用した Action LM（3M、data v0.5.1、INT4）は、grammar ありで 75.0%（12/16）、確信度の gate（confidence gate）も加えると 62.5%（10/16）です。表と読むときの注意は [`evaluation.md`](evaluation.md) の「既存モデルとの比較（TinyLM-Bench の16件）」にあります。16件は傾向を見るためのもので、統計的な結論には足りません。

既存のモデルを PC 上で動かして分かったことです。

- **構造の制約と意味の理解は別:** Needle 2 は schema 妥当が 16/16 でも、厳格一致は 3/16 で、左右を逆に向く誤りが3件ありました。grammar は誤った tool、誤った引数、否定の無視、余分な呼び出しを防げません。
- **評価条件で結果が変わる:** MimiModel は Needle 2 と同じ重みですが、tool の絞り込み、prompt の組み立て、grammar の実装の違いで 1/16 になりました。このプロジェクトでは prompt の形式、greedy decoding、grammar の実装を固定し、Python と C で同じ評価セットを使います。
- **量子化で挙動が変わる:** TinyTalk 2 は、FP32 では「天気は分からない」と答えたのに、組込み用の Q4 では晴れだと答えました。量子化の後は、カテゴリ別の評価をやり直します。
- **語彙の embedding が大きい:** TinyTalk 2 は「8M」と表記されていますが、実際は 19.7M parameter で、差の大部分は 50,257 語の embedding です。
- **日本語の Chat:** 英語の小型モデル（TinyTalk 2 / cardputer-ai、esp32-mind、esp32-ai、esp32-llm）は、日本語の入力に何も返さないか、英語の物語を続けるだけでした。日本語を生成できたのは LLM-jp-3-150M-instruct3 だけで、約 1.25GB の RSS を使い、指示への追従も不安定でした。
- **PC の値の限界:** Windows の RSS は、ESP32 の SRAM / PSRAM の必要量を表しません。実機のメモリは実機で測ります（[`hardware.md`](hardware.md)）。

## 先行例の比較表

| 実装 | 用途 | 規模 | 形式と大きさ | 速度 | 確度 |
|---|---|---:|---|---|---|
| Needle 2 ESP32 | 英語の tool calling | 45M | 約 13.1〜13.7MB | 1.87 tok/s | 一次ソースで確認 |
| slvDev/esp32-ai | TinyStories の文生成 | 28.9M（stored） | 4-bit PLE、14.9MB | 9.88 tok/s | 一次ソースで確認 |
| esp32-mind | TinyStories の文生成 | 11.5M | int4（group 128）、5.97MB | 14.22 tok/s | 速度は一次ソース、規模は PC で確認 |
| doryiii/esp32-llm | 小型 Llama の実験 | 3.1M（stories3M） | INT8（group 64）、3.35MB | 約 12 tok/s（上流）。CoreS3 で 6.5〜7.1 tok/s（forward のみ） | CoreS3 の値は実測 |
| JapaneseTinyAgentLM（Action LM） | 日本語の Action | 3.15M | INT4（group 64）、`.jtlm` 1,971,456 B（tokenizer を含む） | decode 約 105 ms/token。1回の応答は中央値 1,276 ms | 実測（K151） |

## 先行例の調査と主張の範囲

### 調査の範囲

2026-09-30 に、公開情報（英語・日本語・中国語の web、GitHub、Hugging Face、arXiv、Qiita / Zenn、M5Stack / スタックチャンのコミュニティ）を調べ、公開の直前の 2026-10-01 に調べ直しました。「世界初」は主張できません。範囲を絞った主張だけが、「調べた範囲では」の条件つきで成り立ちます。

### 主張できないこと（先行例がある）

| 主張 | 先行例 |
|---|---|
| マイコンで動く最初の言語モデル | esp32-llm（DaveBben、2024、英語）、esp32-ai（slvDev、2026-08、28.9M、英語）、atome-lm（ESP32 / STM32、英語。Python と C の出力の完全一致も主張）、p-for-llm（ESP32-P4、英語）など |
| マイコンで動く最初の tool calling の言語モデル | Needle 2（45M）と Needle 3（29〜121M）の ESP32-S3 移植（pdev-labs、andrisgauracs、vipul-sharma20、PruhaNLP、iammrduncan など）。英語（Needle 3 は英語と欧州の6言語）で、grammar で制約した tool calling もある |
| マイコンで動く最初のオフラインの日本語の命令理解 | Picovoice Rhino（日本語の音声から意図を読み取る。Cortex-M などで動く。言語モデルではなく、文法とスロットに基づく）。Cyberon DSpotter、Sensory（日本語の MCU 対応は一次ソースで未確認） |
| ローカルの LM で動く最初のスタックチャン、ローカルの function calling | AI_StackChan_Ex の Module LLM モード（2024-12、追加モジュール AX630C の NPU で SmolLM-360M の function calling）、ローカル LLM 版の AI スタックチャン（LAN 上の ollama） |
| 最初の超小型の日本語 LM | 日本語 TinyStories（ohtaman、2023-12、1.3M〜62M、PC）、slm-ja-1m（2026-09、1M、PC） |
| ESP32-S3 で動く最初の日本語のニューラルモデル | sanoTTS-jp（559K の日本語 TTS が CoreS3 で実時間で動く。言語モデルではない） |

### 調べた範囲で先行例が見つからなかったこと

主張するときは、次の表現を使ってください。

1. 「日本語の発話からロボットの動作呼び出し（JSON）を決める言語モデルを、ESP32-S3 単体（NPU・外部モジュール・ネットワークなし）で動かした公開事例は、2026年10月1日時点の私たちの調査では見つからなかった。」
2. 「日本語入力を扱う tool calling 型の言語モデルを、マイコン上だけで動かした公開事例も見つからなかった（Needle 2 / 3 の ESP32 移植は英語と欧州の言語のみ）。」
3. 「日本語のテキストを扱う Transformer の言語モデルを、マイコン上で完結して動かした公開例も見当たらなかった（言語モデルではない日本語の処理の先行例はある）。」
4. 「スタックチャンの ESP32-S3 本体だけで、日本語の指示から首振り・表情・うなずきを選ぶ言語モデルを動かした例は見つからなかった（Module LLM などの外付け NPU を使う例はある）。」

2026-10-01 の再調査で確かめたこと:

- Needle 3 の対応言語に日本語はなく、予定にも書かれていない。言語追加の issue（#141、#147）にも日本語はない。コミュニティの fine-tune はトルコ語とブラジルのポルトガル語だけだった。
- 新しい ESP32 への移植（needle-on-cyd、MicroNeedle など）は、どれも英語だけだった。
- 9月に新しく出たスタックチャンの LLM のリポジトリは、どれも LLM をサーバーや PC で動かしている。
- MCU の新しい LM（MCXN947 の 289M、esp32-s3-tinystories など）は、英語か、ESP32 ではなかった。
- `JapaneseTinyAgentLM` と `JapaneseTinyAgentLM-Action-3M` の名前は、Hugging Face、GitHub、PyPI で空いていた。似た名前には UC Berkeley の TinyAgent（2024、edge の tool calling）、dria の Tiny-Agent、PyPI の tinyagent があるが、「Japanese」と「LM」が付くので名前そのものは重ならない。

### 比較するときの書き方

- 大きさは「ESP32 で動く Needle 2 / 3（29〜45M）の約 1/10〜1/15」と書きます。29〜45M は ESP32 に移植されたモデルの大きさです（Needle 3 全体では 29〜121M）。「最小の tool calling のモデル」とは書きません。
- 応答時間（中央値 1,276 ms と、Needle の ESP32 移植の 23〜47 秒）は実測の事実として書けます。ただし、Needle は英語の汎用 tool calling（prompt に schema を入れる方式）で、このモデルは schema を固定した Action 専用であることを併記します。
- TinyLM-Bench の16件の比較は、Needle が日本語を扱わないことを示すものとして書きます。「tool calling の能力で上回った」とは書きません。
- gate、grammar、INT4、マイコン上の tokenizer、実機と PC の出力の一致は、それぞれ単独では新しくありません。特徴は、これらの組み合わせと日本語への適用です。

### 調べきれていないこと

- X / YouTube / Discord など、検索に出にくい投稿（日本語の llama2.c を ESP32 で動かした個人の投稿はありうる）
- 非公開の商用製品（日本語の NLU を MCU に載せた製品）
- 有料・非索引の論文（IEICE / IPSJ の国内発表、J-STAGE）、中国語圏の事例、特許

Needle 3 は対応言語を増やす予定なので、主張を新しく使う前には調べ直してください。

## 一次ソース

- Needle 2 ESP32: https://github.com/andrisgauracs/needle-2-esp32
- slvDev/esp32-ai: https://github.com/slvDev/esp32-ai
- esp32-mind: https://github.com/kortexa-ai/esp32-mind
- doryiii/esp32-llm: https://github.com/doryiii/esp32-llm
- stackchan-idf: https://github.com/ciniml/stackchan-idf
- m5stack/StackChan（K151 の公式 firmware）: https://github.com/m5stack/StackChan
- M5Stack StackChan（K151）の資料: https://docs.m5stack.com/en/StackChan
- M5Stack CoreS3: https://docs.m5stack.com/en/core/CoreS3

各リポジトリの commit と license は、流用や比較の前に固定して確認し直してください。
