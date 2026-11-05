import { test } from "node:test";
import assert from "node:assert/strict";
import { currentPracticeRun, currentPreparationRun, newestRuns } from "../src/lib/learning-status";
import type { CourseDetail, RunSummary, StudySession } from "../src/lib/backend";

const run = (id: string, workflow: string, status: string, day: number, documentId = "doc"): RunSummary => ({ id, workflow, status, summary: "A saved task", startedAt: `2026-10-${day}T00:00:00Z`, documentId });
const course: CourseDetail = { id: "course", title: "Course", documents: [{ id: "doc", filename: "Lesson.pdf", status: "published", pages: 12, lessonCount: 1, postLessonCount: 1, testCount: 2 }], graph: { concepts: [{ id: "doc:goal", title: "Goal", summary: "A goal", sources: [] }], prerequisites: [] } };
const session: StudySession = { id: "s", courseId: "course", status: "active", runIds: ["question", "old-check", "check"], assessment: null, activity: null };

test("practice statuses follow the current session and action, not course history", () => {
  const runs = [run("other-session", "next_activity", "failed", 20), run("old-check", "assessment", "failed", 17), run("question", "next_activity", "running", 18), run("check", "assessment", "running", 19)];
  assert.equal(currentPracticeRun(runs, session)?.id, "question");
  const submitted = { ...session, activity: { id: "a", conceptId: "doc:goal", status: "submitted", hintUsed: false, difficulty: "intermediate", prompt: "Question", choices: [], sources: [] } };
  assert.equal(currentPracticeRun(runs, submitted)?.id, "check");
  assert.equal(currentPracticeRun(runs, { ...submitted, activity: { ...submitted.activity, status: "assessed" } }), undefined);
  assert.equal(currentPracticeRun(runs, { ...session, status: "ended" }), undefined);
  assert.equal(currentPracticeRun(runs, { ...session, notice: "No further questions" }), undefined);
});

test("completed newer preparation suppresses superseded failures regardless of response order", () => {
  const old = run("old", "course_preparation", "failed", 17);
  const ready = run("ready", "course_preparation", "completed", 19);
  assert.equal(currentPreparationRun([ready, old], course), undefined);
  assert.equal(currentPreparationRun([old, ready], course), undefined);
  assert.equal(currentPreparationRun([old], course), undefined); // Existing lessons are usable.
  assert.equal(currentPreparationRun([run("work", "course_preparation", "running", 20), old], course)?.id, "work");
  assert.deepEqual(newestRuns([ready, old]).map(r => r.id), ["ready", "old"]);
});

test("preparation blockers are shown only for the affected material with missing resources", () => {
  const incomplete = { ...course, documents: course.documents.map(d => ({ ...d, postLessonCount: 0 })) };
  assert.equal(currentPreparationRun([run("blocked", "course_preparation", "paused", 19)], incomplete)?.id, "blocked");
  assert.equal(currentPreparationRun([run("other", "course_preparation", "failed", 20, "unrelated")], incomplete), undefined);
  const failedUpload = { ...course, documents: course.documents.map(d => ({ ...d, status: "needs_review" })) };
  assert.equal(currentPreparationRun([run("upload", "course_preparation", "needs_review", 20)], failedUpload)?.id, "upload");
});
