# Space の入力・結果の収集

Hugging Face の Static Space は従来どおりブラウザ内で推論します。`runtime/web/index.html` は毎回の推論後に `POST /feedback` を呼び、R2 に保存できたことを確認してから結果を表示します。入力の送信は任意ではありません。保存できないとき、画面は結果を表示しません。ブラウザが閉じられた、通信が切れた、または改変されたクライアントについて、すべての入力が保存されることまでは保証できません。

## 保存するもの

入力文、モデル SHA-256、gate 前後の JSON、確信度、gate 閾値、token 数、推論時間、または推論エラー、受信日時、記録 ID を1件ずつ `incoming/YYYY-MM-DD/<UUID>.json` に保存します。IP アドレスとブラウザの識別子は R2 の記録に含めません。ブラウザから送られる結果は改変できるため、学習の正解ラベルとみなさず、人が確認してから利用します。

## Cloudflare 側

- Worker: `jtalm-feedback`、`https://jtalm-feedback.yousan-apps.workers.dev/feedback`
- R2: `jtalm-action-feedback`（Standard、`r2.dev` 無効、カスタムドメインなし）
- `incoming/` の記録は90日後に期限切れになる lifecycle rule を設定する。
- Worker の `GET` を公開せず、`POST /feedback` のみ受ける。CORS は Space の実際の iframe origin のみに許可する。Origin は認証ではないため、公開投稿を完全には制限しない。匿名投稿には1訪問元あたり30件/分、全体1000件/分の緩い上限を設ける。
- R2 の閲覧・削除は Cloudflare の所有者アカウントから行う。キーを Space の HTML、JavaScript、リポジトリへ置かない。

## 検証

```powershell
node --test runtime/feedback-worker/test/index.test.js
npx wrangler deploy --dry-run --config runtime/feedback-worker/wrangler.jsonc
npx wrangler r2 bucket dev-url get jtalm-action-feedback
npx wrangler r2 bucket domain list jtalm-action-feedback
npx wrangler r2 bucket lifecycle list jtalm-action-feedback
```

Space のソースは `runtime/web/index.html` と `runtime/web/jtalm.js` です。変更を公開するときは Space `ayousanz/JapaneseTinyAgentLM-Action-3M-demo` の `index.html` を更新します。結果表示だけでなく、R2 の記録と通信失敗時の非表示を確認してください。
