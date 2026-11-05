import type { CourseDetail, RunSummary, StudySession } from "./backend";

export const workingStates = new Set(["queued", "running"]);
export const blockedStates = new Set(["failed", "needs_review", "paused"]);
export function preparationPhase(task: string) {
  if (/Organizer|Relationship|Coordinator|organized map/i.test(task)) return { title: "Organizing your course map", detail: "Grouping topics and checking how the ideas connect." };
  if (/Extract|grounded concepts/i.test(task)) return { title: "Reading your course material", detail: "Finding the source passages for your lessons." };
  if (/Review all|Merge repeated/i.test(task)) return { title: "Finding the key ideas", detail: "Reading each section and bringing related ideas together." };
  if (/lesson|posts|tests/i.test(task)) return { title: "Writing your learning posts", detail: "Turning the key ideas into explanations and practice." };
  return null;
}
export function newestRuns(runs: RunSummary[]) {
  return runs.map((run, index) => ({ run, index })).sort((a, b) => {
    const date = (b.run.startedAt || "").localeCompare(a.run.startedAt || "");
    return date || b.index - a.index;
  }).map(item => item.run);
}

export function currentPracticeRun(runs: RunSummary[], session: StudySession | null) {
  if (!session || session.status !== "active" || session.notice) return undefined;
  const activity = session.activity;
  const workflow = activity?.status === "submitted" ? "assessment" : !activity ? "next_activity" : null;
  if (!workflow) return undefined;
  // A past failed assessment must never become the status for a new question.
  return newestRuns(runs).find(run => session.runIds.includes(run.id) && run.workflow === workflow);
}

export function currentPreparationRun(runs: RunSummary[], course: CourseDetail | null) {
  const seen = new Set<string>();
  return newestRuns(runs).filter(run => {
    if (run.workflow !== "course_preparation") return false;
    const key = run.documentId || "legacy";
    if (seen.has(key)) return false;
    seen.add(key);
    if (workingStates.has(run.status)) return true;
    if (!blockedStates.has(run.status)) return false;
    const doc = course?.documents.find(doc => doc.id === run.documentId);
    // Without a current missing resource, old failures belong in history.
    const expected = course?.graph.concepts.filter(concept => concept.id.startsWith(`${doc?.id}:`)).length || 0;
    return !!doc && (doc.status !== "published" || doc.lessonCount === 0 || doc.lessonCount < expected || (doc.postLessonCount ?? doc.lessonCount) < doc.lessonCount);
  })[0];
}
