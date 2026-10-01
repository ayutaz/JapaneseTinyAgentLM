# Security Policy / セキュリティ

## Reporting a vulnerability / 脆弱性の報告

Please do not open a public issue for security problems. Report them privately with GitHub's
**[Report a vulnerability](https://github.com/ayutaz/JapaneseTinyAgentLM/security/advisories/new)**
(private vulnerability reporting). Japanese or English is fine.

セキュリティの問題は公開の Issue に書かず、上のリンク（GitHub の private vulnerability reporting）から非公開で報告してください。日本語でも英語でもかまいません。

Examples of relevant issues:

- The firmware (`firmware/jtalm_action`) accepting input that crashes the device or bypasses the
  servo limits, the touch stop or the watchdog.
- The `.jtlm` loader (`runtime/host`, firmware) reading out of bounds on a malformed file.
- Scripts that could leak credentials from `.env`.

## Supported versions

Only the latest commit on `main` and the latest model on Hugging Face
([ayousanz/JapaneseTinyAgentLM-Action-3M](https://huggingface.co/ayousanz/JapaneseTinyAgentLM-Action-3M))
are supported.
