const SPACE_ORIGIN = "https://ayousanz-japanesetinyagentlm-action-3m-demo.static.hf.space";
const MODEL_SHA256 = "d649c1ad0c00c40f9e0dbb4b1bc1360cfdcf14e904f16866a98c2aa8baf6f314";
const MAX_BODY_BYTES = 4096;
const MAX_INPUT_CHARS = 500;

function json(body, status, cors = false) {
  const headers = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };
  if (cors) {
    headers["access-control-allow-origin"] = SPACE_ORIGIN;
    headers.vary = "Origin";
  }
  return new Response(JSON.stringify(body), { status, headers });
}

function validActions(value) {
  return Array.isArray(value) && value.length <= 2 && value.every(
    (item) => item && typeof item === "object" && !Array.isArray(item)
      && typeof item.name === "string" && item.name.length <= 40
      && item.arguments && typeof item.arguments === "object" && !Array.isArray(item.arguments)
  );
}

function validPayload(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  if (value.schema_version !== 1 || value.model_sha256 !== MODEL_SHA256) return false;
  if (typeof value.input !== "string" || !value.input.trim()
      || [...value.input].length > MAX_INPUT_CHARS) return false;
  if (!Number.isFinite(value.elapsed_ms) || value.elapsed_ms < 0 || value.elapsed_ms > 600000) return false;
  if (value.outcome === "error") {
    return typeof value.error === "string" && value.error.length > 0 && value.error.length <= 200;
  }
  return value.outcome === "success"
    && validActions(value.raw_actions) && validActions(value.actions)
    && Number.isFinite(value.min_prob) && value.min_prob >= 0 && value.min_prob <= 1
    && Number.isFinite(value.gate_threshold) && value.gate_threshold >= 0
    && value.gate_threshold <= 1
    && Number.isInteger(value.tokens) && value.tokens >= 0 && value.tokens <= 4096;
}

async function readLimited(request) {
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > MAX_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/feedback") return json({ error: "not_found" }, 404);
    const allowedOrigin = request.headers.get("origin") === SPACE_ORIGIN;
    if (!allowedOrigin) return json({ error: "forbidden" }, 403);
    if (request.method === "OPTIONS") {
      if (request.headers.get("access-control-request-method") !== "POST") {
        return json({ error: "method_not_allowed" }, 405, true);
      }
      return new Response(null, { status: 204, headers: {
        "access-control-allow-origin": SPACE_ORIGIN,
        "access-control-allow-methods": "POST, OPTIONS",
        "access-control-allow-headers": "content-type",
        "access-control-max-age": "3600",
        vary: "Origin",
        "cache-control": "no-store",
      } });
    }
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405, true);
    if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
      return json({ error: "unsupported_media_type" }, 415, true);
    }
    const declaredLength = Number(request.headers.get("content-length"));
    if (Number.isFinite(declaredLength) && declaredLength > MAX_BODY_BYTES) {
      return json({ error: "too_large" }, 413, true);
    }
    let body;
    try {
      const bytes = await readLimited(request);
      if (!bytes) return json({ error: "too_large" }, 413, true);
      body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } catch {
      return json({ error: "invalid_json" }, 400, true);
    }
    if (!validPayload(body)) return json({ error: "invalid_payload" }, 400, true);

    try {
      const visitorKey = request.headers.get("cf-connecting-ip") || "unknown";
      const [visitor, global] = await Promise.all([
        env.VISITOR_LIMIT.limit({ key: visitorKey }),
        env.GLOBAL_LIMIT.limit({ key: "feedback" }),
      ]);
      if (!visitor.success || !global.success) return json({ error: "rate_limited" }, 429, true);

      const id = crypto.randomUUID();
      const receivedAt = new Date().toISOString();
      const key = `incoming/${receivedAt.slice(0, 10)}/${id}.json`;
      const record = {
        schema_version: 1,
        id,
        received_at: receivedAt,
        model_sha256: MODEL_SHA256,
        input: body.input,
        outcome: body.outcome,
        elapsed_ms: body.elapsed_ms,
        ...(body.outcome === "success" ? {
          raw_actions: body.raw_actions,
          actions: body.actions,
          min_prob: body.min_prob,
          gate_threshold: body.gate_threshold,
          tokens: body.tokens,
        } : { error: body.error }),
      };
      await env.FEEDBACK.put(key, JSON.stringify(record), {
        httpMetadata: { contentType: "application/json; charset=utf-8" },
      });
      return json({ id }, 201, true);
    } catch {
      return json({ error: "storage_unavailable" }, 503, true);
    }
  },
};
