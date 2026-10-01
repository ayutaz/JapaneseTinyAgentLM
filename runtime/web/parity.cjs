// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 ayutaz
//
// Compares the WebAssembly build with the host runtime (both -DJTLM_ACC=float, --grammar):
//   node runtime/web/parity.cjs <model.jtlm> <prompts.txt> <host.jsonl>
// prompts.txt has one prompt per line; host.jsonl is `build/jtalm -m <model> --grammar -i
// prompts.txt` from a host build with CFLAGS="-O2 -DJTLM_ACC=float".
const fs = require("fs");
const path = require("path");

const lines = (file) => fs.readFileSync(file, "utf8").split("\n").filter((l) => l.length);

(async () => {
  const [modelPath, promptsPath, hostPath] = process.argv.slice(2);
  // jtalm.js is built with -sMODULARIZE; load it as CommonJS whatever the package type is.
  const src = fs.readFileSync(path.join(__dirname, "jtalm.js"), "utf8");
  const mod = { exports: {} };
  new Function("module", "exports", "require", "__dirname", "__filename", src)(
    mod, mod.exports, require, __dirname, path.join(__dirname, "jtalm.js"));
  const M = await mod.exports();

  const image = fs.readFileSync(modelPath);
  const p = M._malloc(image.length);
  M.HEAPU8.set(image, p);
  if (M._web_init(p, image.length) !== 0) throw new Error("web_init failed");
  const predict = M.cwrap("web_predict", "string", ["string"]);

  const prompts = lines(promptsPath);
  const host = lines(hostPath).map(JSON.parse);
  let sameOutput = 0, sameProb = 0;
  const t0 = Date.now();
  prompts.forEach((text, i) => {
    const r = JSON.parse(predict(text));
    if (JSON.stringify(r.raw) === JSON.stringify(JSON.parse(host[i].output))) sameOutput++;
    if (r.min_prob === host[i].min_prob) sameProb++;
  });
  const ms = (Date.now() - t0) / prompts.length;
  console.log(JSON.stringify({ prompts: prompts.length, sameOutput, sameProb, msPerPrompt: ms }));
  process.exit(sameOutput === prompts.length && sameProb === prompts.length ? 0 : 1);
})();
