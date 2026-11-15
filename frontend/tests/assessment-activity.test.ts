import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AssessmentActivity } from "../src/components/assessment-activity";
import type { TutorHandoff } from "../src/components/tutor-handoffs";

test("assessment activity associates recorded events with their handoff and omits private payloads", () => {
  const handoff: TutorHandoff = { runId: "assessment-1", status: "completed", summary: "", retryable: false, result: { assessmentId: "a1" }, request: { requestId: "req-1", parentRunId: null, targetAgent: "assessing", task: "assess_answer", conceptId: "c1" } };
  const html = renderToStaticMarkup(createElement(AssessmentActivity, { handoffs: [handoff], conceptName: () => "Attention", runs: [
    { id: "other", events: [{ type: "agent.step", at: "2026-11-15T00:00:00Z", payload: { task: "Unrelated step" } }] },
    { id: "assessment-1", events: [
      { type: "agent.step", at: "2026-11-15T00:00:01Z", payload: { task: "Check response evidence", detail: "Evaluate the answer", tool: "assess_response" } },
      { type: "runtime.validation", at: "2026-11-15T00:00:02Z", payload: { status: "accepted", scope: "learner_state", summary: "Saved", committed: { secret: "private payload" } } },
    ] },
  ] }));
  assert.match(html, /Check response evidence/);
  assert.match(html, /Tool: assess_response/);
  assert.match(html, /Validation accepted/);
  assert.match(html, /Scope: learner state/);
  assert.doesNotMatch(html, /Unrelated step|private payload/);
});

test("assessment activity explains when a handoff has no recorded events", () => {
  const handoff: TutorHandoff = { runId: "missing", status: "queued", summary: "Waiting", retryable: false, result: null, request: { requestId: "req", parentRunId: null, targetAgent: "assessing", task: "assess_answer" } };
  const html = renderToStaticMarkup(createElement(AssessmentActivity, { handoffs: [handoff], runs: [], conceptName: id => id }));
  assert.match(html, /No detailed activity was recorded/);
});
