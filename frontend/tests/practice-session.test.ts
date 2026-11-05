import { test } from "node:test";
import assert from "node:assert/strict";
import { concepts } from "../src/lib/demo-data";
import { practiceBank } from "../src/lib/practice-bank";
import {
  getConceptEvidence,
  getLearnerConcepts,
} from "../src/lib/learner-evidence";
import {
  initialPractice,
  migrateDescent,
  practiceReducer,
  recommendedConcept,
  restorePractice,
  sessionAttempts,
  sessionIndependent,
  unmetPrerequisites,
  type PracticeSnapshot,
} from "../src/lib/practice-session";

const at = "2026-10-18T02:00:00.000Z";
test("a blocked concept recommendation follows prerequisites to an eligible foundation", () => {
  const state = start("adam");
  const next = recommendedConcept("adam", state.records)!;
  assert.equal(next.id, "descent");
  assert.equal(unmetPrerequisites(next.id, state.records).length, 0);
});
function start(id = "rate") {
  let state = practiceReducer(initialPractice(), {
    type: "load",
    value: initialPractice(),
  });
  state = practiceReducer(state, { type: "activate", conceptId: id });
  return state;
}
function answer(state: PracticeSnapshot, correct = true, hint = false) {
  const question =
    practiceBank[state.conceptId][state.records[state.conceptId].question];
  state = practiceReducer(state, {
    type: "answer",
    value: correct
      ? question.correctId
      : question.choices.find((choice) => choice.id !== question.correctId)!.id,
  });
  if (hint) state = practiceReducer(state, { type: "hint" });
  return practiceReducer(state, { type: "submit", at });
}
function next(state: PracticeSnapshot) {
  return practiceReducer(state, { type: "next" });
}

test("every course concept has two distinct usable four-option MC questions", () => {
  for (const concept of concepts) {
    const bank = practiceBank[concept.id];
    assert.equal(bank.length, 2);
    assert.notEqual(bank[0].prompt, bank[1].prompt);
    for (const question of bank) {
      assert.equal(
        new Set(question.choices.map((choice) => choice.id)).size,
        4,
      );
      assert.ok(
        question.choices.some((choice) => choice.id === question.correctId),
      );
      assert.ok(question.hint);
    }
  }
});
test("a deep-linked blocked concept cannot submit an assessment", () => {
  const state = start("adam");
  assert.ok(unmetPrerequisites("adam", state.records).length);
  const result = answer(state);
  assert.equal(result.records.adam.attempts, 0);
  assert.equal(result.records.adam.status, "unassessed");
});
test("distinct checks update only their own concept and duplicate submission is harmless", () => {
  let state = answer(start());
  assert.equal(state.records.rate.status, "developing");
  assert.equal(
    practiceReducer(state, { type: "submit", at }).records.rate.attempts,
    1,
  );
  state = answer(next(state));
  assert.equal(state.records.rate.status, "demonstrated");
  assert.equal(state.records.rate.history.length, 2);
  assert.equal(
    getConceptEvidence(
      concepts.find((c) => c.id === "descent")!,
      state,
    ).overall,
    "developing",
  );
  assert.equal(
    getLearnerConcepts(state).find((c) => c.id === "rate")!.state,
    "demonstrated",
  );
});
test("hinted answers remain diagnostic evidence and session summary excludes them from independent checks", () => {
  const state = answer(start(), true, true);
  assert.equal(state.records.rate.history[0].hinted, true);
  assert.equal(sessionIndependent(state.records.rate), 0);
  assert.equal(state.records.rate.status, "developing");
  assert.equal(
    getConceptEvidence(
      concepts.find((c) => c.id === "rate")!,
      state,
    ).levels.intermediate.assisted,
    1,
  );
});
test("conflicting evidence on a demonstrated prerequisite schedules review and blocks its dependent", () => {
  const state = answer(start("gradients"), false);
  assert.equal(state.records.gradients.status, "review_due");
  assert.equal(state.records.gradients.history.length, 1);
  assert.ok(unmetPrerequisites("descent", state.records).includes("gradients"));
  assert.match(
    getConceptEvidence(
      concepts.find((c) => c.id === "gradients")!,
      state,
    ).reason("intermediate"),
    /conflicts/,
  );
});
test("switching concepts preserves pending answers and completed evidence", () => {
  let state = answer(start());
  state = practiceReducer(state, { type: "activate", conceptId: "functions" });
  state = practiceReducer(state, { type: "answer", value: "b" });
  state = practiceReducer(state, { type: "activate", conceptId: "rate" });
  assert.equal(state.records.rate.feedback, "success");
  assert.equal(state.records.functions.answer, "b");
  const restored = restorePractice(JSON.parse(JSON.stringify(state)))!;
  assert.ok(restored);
  assert.equal(restored.records.functions.answer, "b");
});
test("a new session has its own before-state and attempt slice while all history stays available", () => {
  let state = answer(next(answer(start())));
  state = practiceReducer(state, { type: "end" });
  state = practiceReducer(state, { type: "restart" });
  assert.equal(state.records.rate.sessionBefore, "demonstrated");
  assert.equal(sessionAttempts(state.records.rate).length, 0);
  assert.equal(state.records.rate.history.length, 2);
  assert.equal(sessionIndependent(state.records.rate), 0);
});
test("legacy gradient-descent selections and history migrate without leaking to another concept", () => {
  const legacy = {
    answer: "b",
    question: 0,
    hinted: false,
    independentQuestions: [0],
    successes: 1,
    attempts: 1,
    feedback: "success",
    history: [
      {
        id: "attempt-1",
        question: 0,
        answer: "b",
        correct: true,
        hinted: false,
        at,
      },
    ],
  };
  const state = migrateDescent(legacy)!;
  assert.ok(state);
  assert.equal(state.records.descent.answer, "b");
  assert.equal(state.records.descent.history[0].conceptId, "descent");
  assert.equal(sessionAttempts(state.records.descent).length, 0);
  assert.equal(
    getConceptEvidence(
      concepts.find((c) => c.id === "rate")!,
      state,
    ).history.length,
    0,
  );
  assert.equal(
    restorePractice({
      ...state,
      records: {
        ...state.records,
        descent: { ...state.records.descent, question: 99 },
      },
    }),
    null,
  );
});
test("demonstrating a concept recommends an eligible dependent", () => {
  const state = answer(next(answer(start("descent"))));
  assert.equal(recommendedConcept("descent", state.records)?.id, "sgd");
});
