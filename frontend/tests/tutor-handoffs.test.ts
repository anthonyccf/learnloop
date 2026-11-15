import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { TutorHandoffs, type TutorHandoff } from "../src/components/tutor-handoffs";

test("handoffs show agent results and offer retries only for the current run", () => {
  const expert: TutorHandoff = { runId: "run-1", status: "completed", summary: "", retryable: false, result: { sourceCount: 2 }, request: { requestId: "req-1", parentRunId: "run-1", targetAgent: "expert", task: "generate_lesson", conceptId: "c1", difficulty: "basic" } };
  const assessing: TutorHandoff = { runId: "run-2", status: "failed", summary: "Assessment interrupted.", retryable: true, result: null, request: { requestId: "req-2", parentRunId: "run-1", targetAgent: "assessing", task: "assess_answer" } };
  const props = { handoffs: [expert, assessing], lastRunId: "run-2", busy: false, onRetry: () => {}, conceptName: () => "Attention" };
  const html = renderToStaticMarkup(createElement(TutorHandoffs, props));
  assert.match(html, /Tutor → Expert/);
  assert.match(html, /Source-validated lesson ready/);
  assert.match(html, /Attention · basic/);
  assert.match(html, /Assessment interrupted/);
  assert.match(html, /Retry handoff/);
  const stale = renderToStaticMarkup(createElement(TutorHandoffs, { ...props, lastRunId: "other" }));
  assert.doesNotMatch(stale, /Retry handoff/);
});
