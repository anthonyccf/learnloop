import assert from "node:assert/strict";
import test from "node:test";
import { expertHandoffEvents } from "../src/components/expert-tutor-handoffs";
import type { TutorHandoff } from "../src/components/tutor-handoffs";

const makeHandoff = (id: string, task: string): TutorHandoff => ({ runId: "run-1", status: "completed", summary: "", retryable: false, result: null, request: { requestId: id, parentRunId: "run-1", targetAgent: "expert", task } });

test("Expert handoffs show their own recorded Expert steps, not Tutor or unrelated activity", () => {
  const question = makeHandoff("q", "generate_question");
  const lesson = makeHandoff("l", "generate_lesson");
  const events = [
    { type: "agent.step", at: "1", payload: { role: "tutoring", detail: "Choose question" } },
    { type: "agent.step", at: "2", payload: { role: "expert", detail: "Preparing a source-grounded question" } },
    { type: "agent.step", at: "3", payload: { role: "expert", detail: "A source-validated question is ready" } },
    { type: "agent.step", at: "4", payload: { role: "expert", detail: "Preparing a lesson" } },
    { type: "run.status", at: "5", payload: { status: "completed" } },
  ];
  assert.deepEqual(expertHandoffEvents(question, events, [question, lesson]).map(item => item.at), ["2", "3"]);
  assert.deepEqual(expertHandoffEvents(lesson, events, [question, lesson]).map(item => item.at), ["4"]);
  assert.deepEqual(expertHandoffEvents(question, events, [question]).map(item => item.at), ["2", "3", "4"]);
});
