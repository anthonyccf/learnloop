import { gzipSync } from "node:zlib";
import { NextRequest } from "next/server";

// Only expose the local single-owner API's public projections.
const routes = [
  /^courses(?:\/[^/]+(?:\/(?:documents|rename|materials|organize|learner-state|sessions|search|runs|assessments))?)?$/,
  /^courses\/[^/]+\/plan(?:\/revise)?$/,
  /^courses\/[^/]+\/concepts\/[^/]+\/target$/,
  /^documents\/[^/]+\/(?:rename|review|materials|analyze|pages\/\d+(?:\/slide)?)$/,
  /^sessions\/[^/]+(?:\/(?:end|next|chat))?$/,
  /^activities\/[^/]+\/(?:hint|responses|present)$/,
  /^submissions\/[^/]+$/,
  /^agent-activity\/runs\/[^/]+(?:\/(?:commands|events))?$/,
];

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const resource = path.join("/");
  const conceptTarget = path.length === 5 && path[0] === "courses" && path[2] === "concepts" && path[4] === "target";
  if (path.some((p, index) => !(conceptTarget && index === 3 ? /^[a-zA-Z0-9_:-]+$/ : /^[a-zA-Z0-9_-]+$/).test(p)) || !routes.some(r => r.test(resource)))
    return Response.json({ detail: "Unknown API route." }, { status: 404 });
  const url = new URL(request.url);
  const expectedOrigin = `${url.protocol}//${request.headers.get("host") || url.host}`;
  if (request.method === "POST" && request.headers.get("origin") !== expectedOrigin)
    return Response.json({ detail: "Use this workspace to submit requests." }, { status: 403 });
  const token = process.env.LEARNLOOP_API_TOKEN;
  if (!token) return Response.json({ detail: "The backend connection is not configured." }, { status: 503 });
  const length = Number(request.headers.get("content-length") || 0);
  if (length > 21 * 1024 * 1024) return Response.json({ detail: "Upload files up to 20 MiB." }, { status: 413 });
  try {
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    for (const key of ["content-type", "last-event-id"]) {
      const value = request.headers.get(key);
      if (value) headers.set(key, value);
    }
    const response = await fetch(`${process.env.LEARNLOOP_BACKEND_URL || "http://127.0.0.1:8010"}/api/${resource}${request.nextUrl.search}`, {
      method: request.method, headers, cache: "no-store", redirect: "error",
      body: request.method === "POST" ? await request.arrayBuffer() : undefined,
      signal: request.signal,
    });
    const type = response.headers.get("content-type") || "application/json";
    const shared = { "Content-Type": type, "Cache-Control": "no-store" };
    // Live activity stays streamed. Every other response is one buffered body
    // with Content-Length. Chunked tunnel responses fail in Chrome over HTTP/3.
    if (type.includes("text/event-stream")) {
      return new Response(response.body, { status: response.status, headers: { ...shared, "X-Accel-Buffering": "no" } });
    }
    const payload = Buffer.from(await response.arrayBuffer());
    const acceptsGzip = /\bgzip\b/.test(request.headers.get("accept-encoding") || "");
    if (acceptsGzip && type.includes("json") && payload.byteLength >= 1024) {
      const packed = gzipSync(payload);
      return new Response(packed, { status: response.status, headers: { ...shared, "Content-Encoding": "gzip", "Content-Length": String(packed.byteLength), Vary: "Accept-Encoding" } });
    }
    return new Response(payload, { status: response.status, headers: { ...shared, "Content-Length": String(payload.byteLength) } });
  } catch {
    return Response.json({ detail: "Cannot reach the learning server. Check that the backend is running, then retry." }, { status: 502 });
  }
}
export const GET = proxy;
export const POST = proxy;
