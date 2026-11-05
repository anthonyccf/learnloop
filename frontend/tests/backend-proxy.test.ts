import { test } from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { GET, POST } from "../src/app/api/backend/[...path]/route";
import { api } from "../src/lib/backend";

test("backend bridge keeps credentials private and forwards uploads and streamed events", async () => {
  const originalFetch = globalThis.fetch;
  const previousToken = process.env.LEARNLOOP_API_TOKEN;
  const previousUrl = process.env.LEARNLOOP_BACKEND_URL;
  process.env.LEARNLOOP_API_TOKEN = "test-private-token";
  process.env.LEARNLOOP_BACKEND_URL = "http://127.0.0.1:8010";
  const calls: { url: string; options: RequestInit }[] = [];
  globalThis.fetch = (async (url, options) => {
    calls.push({ url: String(url), options: options! });
    return new Response("data: {\"sequence\":1}\n\n", { status: 202, headers: { "Content-Type": "text/event-stream" } });
  }) as typeof fetch;
  const context = (path: string) => ({ params: Promise.resolve({ path: path.split("/") }) });
  try {
    const form = new FormData(); form.append("file", new Blob(["actual material"]), "notes.txt");
    const request = new NextRequest("http://127.0.0.1:3100/api/backend/courses/course-1/documents", { method: "POST", headers: { Origin: "http://127.0.0.1:3100", Host: "127.0.0.1:3100" }, body: form });
    const response = await POST(request, context("courses/course-1/documents"));
    assert.equal(response.status, 202);
    assert.equal(response.headers.get("Authorization"), null);
    assert.equal(new Headers(calls[0].options.headers).get("Authorization"), "Bearer test-private-token");
    const forwarded = new Request(calls[0].url, calls[0].options);
    const uploaded = (await forwarded.formData()).get("file") as File;
    assert.equal(uploaded.name, "notes.txt"); assert.equal(await uploaded.text(), "actual material");
    const stream = await GET(new NextRequest("http://127.0.0.1:3100/api/backend/agent-activity/runs/run-1/events?after_sequence=4", { headers: { "Last-Event-ID": "5" } }), context("agent-activity/runs/run-1/events"));
    assert.match(calls[1].url, /after_sequence=4$/);
    assert.equal(new Headers(calls[1].options.headers).get("Last-Event-ID"), "5");
    assert.equal(await stream.text(), "data: {\"sequence\":1}\n\n");
    assert.equal(stream.headers.get("Cache-Control"), "no-store");
    const forbidden = await POST(new NextRequest("http://127.0.0.1:3100/api/backend/courses", { method: "POST", headers: { Origin: "https://untrusted.example" } }), context("courses"));
    assert.equal(forbidden.status, 403); assert.equal(calls.length, 2);
    const unknown = await GET(new NextRequest("http://127.0.0.1:3100/api/backend/admin"), context("admin"));
    assert.equal(unknown.status, 404);
    for (const path of ["courses/course-1/plan", "courses/course-1/plan/revise", "activities/activity-1/present", "courses/course-1/concepts/doc-1:concept-1/target"]) {
      const method = path.endsWith("/plan") ? "GET" : "POST";
      const request = new NextRequest(`http://127.0.0.1:3100/api/backend/${path}`, { method, headers: { Origin: "http://127.0.0.1:3100", Host: "127.0.0.1:3100" } });
      assert.equal((await (method === "GET" ? GET : POST)(request, context(path))).status, 202);
      assert.equal(calls.at(-1)?.url, `http://127.0.0.1:8010/api/${path}`);
    }
    for (const path of ["courses/course-1/plan/admin", "courses/course-1/concepts/../target", "activities/http:evil/present"]) {
      assert.equal((await GET(new NextRequest("http://127.0.0.1:3100/api/backend/blocked"), context(path))).status, 404);
    }
    const png = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
    globalThis.fetch = (async () => new Response(png, { headers: { "Content-Type": "image/png" } })) as typeof fetch;
    const slide = await GET(new NextRequest("http://127.0.0.1:3100/api/backend/documents/doc-1/pages/2/slide"), context("documents/doc-1/pages/2/slide"));
    assert.equal(slide.status, 200);
    assert.equal(slide.headers.get("Content-Type"), "image/png");
    assert.equal(slide.headers.get("Content-Length"), String(png.byteLength));
    assert.deepEqual(new Uint8Array(await slide.arrayBuffer()), png);
    globalThis.fetch = (async () => { throw new Error("private upstream failure"); }) as typeof fetch;
    const unavailable = await GET(new NextRequest("http://127.0.0.1:3100/api/backend/courses"), context("courses"));
    assert.equal(unavailable.status, 502); assert.doesNotMatch(await unavailable.text(), /private upstream failure|test-private-token/);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousToken === undefined) delete process.env.LEARNLOOP_API_TOKEN; else process.env.LEARNLOOP_API_TOKEN = previousToken;
    if (previousUrl === undefined) delete process.env.LEARNLOOP_BACKEND_URL; else process.env.LEARNLOOP_BACKEND_URL = previousUrl;
  }
});

test("backend bridge buffers json and compresses large responses", async () => {
  const originalFetch = globalThis.fetch;
  const previousToken = process.env.LEARNLOOP_API_TOKEN;
  process.env.LEARNLOOP_API_TOKEN = "test-private-token";
  const payload = JSON.stringify({ materials: "lesson ".repeat(300) });
  globalThis.fetch = (async () => new Response(payload, { headers: { "Content-Type": "application/json" } })) as typeof fetch;
  try {
    const response = await GET(new NextRequest("http://127.0.0.1:3100/api/backend/courses/course-1/materials", { headers: { "Accept-Encoding": "gzip" } }), { params: Promise.resolve({ path: ["courses", "course-1", "materials"] }) });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("Content-Encoding"), "gzip");
    assert.equal(response.headers.get("Content-Length"), String((await response.clone().arrayBuffer()).byteLength));
    const { gunzipSync } = await import("node:zlib");
    assert.equal(gunzipSync(Buffer.from(await response.arrayBuffer())).toString(), payload);
  } finally {
    globalThis.fetch = originalFetch;
    if (previousToken === undefined) delete process.env.LEARNLOOP_API_TOKEN; else process.env.LEARNLOOP_API_TOKEN = previousToken;
  }
});

test("api rejects an unreadable success body", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } })) as typeof fetch;
  try {
    await assert.rejects(api("courses"), /unreadable response/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
