import assert from "node:assert/strict";
import { test } from "node:test";
import worker from "../src/index.js";

const origin = "https://ayousanz-japanesetinyagentlm-action-3m-demo.static.hf.space";
const model = "d649c1ad0c00c40f9e0dbb4b1bc1360cfdcf14e904f16866a98c2aa8baf6f314";
const sample = {
  schema_version: 1, model_sha256: model, input: "右を向いて", outcome: "success",
  raw_actions: [{ name: "look", arguments: { direction: "right", amount: "normal" } }],
  actions: [{ name: "look", arguments: { direction: "right", amount: "normal" } }],
  min_prob: 0.95, gate_threshold: 0.83673, tokens: 8, elapsed_ms: 50,
};

function fixture({ saveFails = false, rateLimited = false } = {}) {
  const saved = [];
  const env = {
    FEEDBACK: { async put(key, value) { if (saveFails) throw Error("failed"); saved.push({ key, value }); } },
    VISITOR_LIMIT: { async limit() { return { success: !rateLimited }; } },
    GLOBAL_LIMIT: { async limit() { return { success: true }; } },
  };
  return { env, saved };
}

function request(payload = sample, headers = {}) {
  return new Request("https://example.workers.dev/feedback", {
    method: "POST", headers: { origin, "content-type": "application/json", ...headers },
    body: JSON.stringify(payload),
  });
}

test("stores a valid result and confirms only after R2 put", async () => {
  const { env, saved } = fixture();
  const response = await worker.fetch(request(), env);
  assert.equal(response.status, 201);
  assert.equal(saved.length, 1);
  assert.match(saved[0].key, /^incoming\/\d{4}-\d{2}-\d{2}\/[0-9a-f-]+\.json$/);
  const record = JSON.parse(saved[0].value);
  assert.equal(record.input, sample.input);
  assert.deepEqual(record.actions, sample.actions);
  assert.equal(record.model_sha256, model);
  assert.equal(record.ip, undefined);
});

test("never acknowledges failed storage", async () => {
  const { env } = fixture({ saveFails: true });
  assert.equal((await worker.fetch(request(), env)).status, 503);
});

test("rejects reads and foreign origins", async () => {
  const { env, saved } = fixture();
  assert.equal((await worker.fetch(new Request("https://example.workers.dev/feedback", { headers: { origin } }), env)).status, 405);
  assert.equal((await worker.fetch(request(sample, { origin: "https://other.example" }), env)).status, 403);
  assert.equal(saved.length, 0);
});

test("rejects malformed, oversized, and rate-limited submissions", async () => {
  const { env, saved } = fixture();
  assert.equal((await worker.fetch(request({ ...sample, input: "" }), env)).status, 400);
  assert.equal((await worker.fetch(request({ ...sample, input: "あ".repeat(1500) }), env)).status, 413);
  assert.equal((await worker.fetch(request(sample, { "content-type": "text/plain" }), env)).status, 415);
  assert.equal((await worker.fetch(request(), fixture({ rateLimited: true }).env)).status, 429);
  assert.equal(saved.length, 0);
});

test("stores inference errors too", async () => {
  const { env, saved } = fixture();
  const response = await worker.fetch(request({ schema_version: 1, model_sha256: model,
    input: "右を向いて", outcome: "error", error: "generation failed", elapsed_ms: 1 }), env);
  assert.equal(response.status, 201);
  assert.equal(JSON.parse(saved[0].value).error, "generation failed");
});

test("allows only POST preflight from the Space", async () => {
  const { env } = fixture();
  const response = await worker.fetch(new Request("https://example.workers.dev/feedback", {
    method: "OPTIONS", headers: { origin, "access-control-request-method": "POST" },
  }), env);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get("access-control-allow-origin"), origin);
});
