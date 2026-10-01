# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ayutaz
"""M2.5 smoke test: ask a vLLM OpenAI-compatible server for a few JSON outputs.

This only checks that the generation path works end to end. Its outputs are not training data.
"""

import argparse
import json
from pathlib import Path

from openai import OpenAI

SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "items": {"type": "string"}, "maxItems": 5}},
    "required": ["sentences"],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    client = OpenAI(base_url=args.base_url, api_key="EMPTY")
    rows = []
    for seed in range(3):
        resp = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": "Write 3 short greetings in Japanese as JSON."}],
            temperature=0.7,
            seed=seed,
            max_tokens=256,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "greetings", "schema": SCHEMA},
            },
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        text = resp.choices[0].message.content or ""
        rows.append({"seed": seed, "parsed": json.loads(text), "usage": resp.usage.model_dump()})
    args.out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
