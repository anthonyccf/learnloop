import { test } from "node:test";
import assert from "node:assert/strict";
import { knowledgeViewUrl, readKnowledgeView } from "../src/lib/knowledge-view";

test("a map deep link preserves concept, combined filters and list preference on reload", () => {
  const view = readKnowledgeView(new URLSearchParams("concept=doc%3Akv-cache&level=advanced&q=cache+%26+memory&topic=topic-2&material=doc&state=developing&display=list"));
  const url = new URL(knowledgeViewUrl(view), "http://localhost");
  assert.deepEqual(readKnowledgeView(url.searchParams), view);
  assert.equal(view.query, "cache & memory");
  assert.equal(view.id, "doc:kv-cache");
});

test("course structure does not retain a hidden personal evidence filter", () => {
  const view = readKnowledgeView(new URLSearchParams("view=course&state=developing&topic=attention&level=advanced"));
  assert.equal(view.status, "all");
  assert.equal(view.topic, "attention");
  assert.equal(view.level, "advanced");
  const url = new URL(knowledgeViewUrl({ ...view, status: "demonstrated" }), "http://localhost");
  assert.equal(url.searchParams.has("state"), false);
});

test("the default map opens without an automatic concept selection and tolerates invalid preferences", () => {
  const view = readKnowledgeView(new URLSearchParams("level=unsupported&state=unknown&display=unknown"));
  assert.equal(view.id, "");
  assert.equal(view.level, "intermediate");
  assert.equal(view.status, "all");
  assert.equal(view.display, "auto");
  assert.equal(knowledgeViewUrl(view), "/map");
});
