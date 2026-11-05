import assert from "node:assert/strict";
import test from "node:test";
import { overallState, targetDifficulty, type LearnerState } from "../src/lib/backend";

test("overall status uses the target and does not promote lower-level evidence", () => {
  const learner: LearnerState = { version: 1, concepts: { a: { basic: { state: "demonstrated" }, intermediate: { state: "developing" } } } };
  assert.equal(overallState({ id: "a", targetDifficulty: "basic" }, learner), "demonstrated");
  assert.equal(overallState({ id: "a", targetDifficulty: "advanced" }, learner), "unassessed");
  assert.equal(overallState({ id: "a" }, learner), "developing");
  assert.equal(overallState({ id: "a", targetDifficulty: "basic" }, { ...learner, overallStates: { a: "review_due" } }), "review_due");
});

test("curriculum layers determine evidence and mastery without mixing assessment history", () => {
  const learner: LearnerState = { version: 1, concepts: { a: { basic: { state: "demonstrated" }, intermediate: { state: "developing" } } } };
  const before = JSON.stringify(learner);
  for (const layer of ["basic", "intermediate", "advanced"] as const) {
    const concept = { id: "a", targetDifficulty: "intermediate" as const, curriculum: { layer } };
    assert.equal(targetDifficulty(concept), layer);
    assert.equal(overallState(concept, learner), layer === "basic" ? "demonstrated" : layer === "intermediate" ? "developing" : "unassessed");
  }
  assert.equal(JSON.stringify(learner), before);
});
