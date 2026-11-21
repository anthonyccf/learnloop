export type CurriculumObjective = { conceptId: string; layer: Difficulty; teaches: string; assumes: string[]; adds: string };
export type Course = { id: string; title: string };
export type Difficulty = "basic" | "intermediate" | "advanced";
export type Reference = { documentId: string; label: string; page?: number };
export type CourseDetail = Course & {
  release?: { id: string; version: number; sha256: string } | null;
  publishedMaterials?: { id: string; filename: string }[];
  documents: { id: string; filename: string; status: string; pages: number; lessonCount: number; postLessonCount?: number; testCount: number; sourceWarnings?: { conceptId: string; title?: string; message: string }[];
    coverage?: { analysisVersion?: number; processedPassages?: number; selectedPassages?: number; totalPassages?: number; reviewedSections?: number; totalSections?: number } }[];
  graph: { concepts: { id: string; title: string; summary: string; curriculum?: CurriculumObjective | null; targetDifficulty?: Difficulty; sources: { chunkId: string; quote: string }[] }[];
    prerequisites: { prerequisite: string; dependent: string; rationale?: string }[];
    topics?: { id: string; title: string; summary: string; parentId?: string | null; conceptIds: string[] }[];
    related?: { first: string; second: string; rationale: string }[];
    organization?: { conceptCount: number; groupedConceptCount: number; topicCount: number; documentCount: number; reviewed: boolean } };
};
export type LearnerState = { version: number; concepts: Record<string, Record<string, { state: string; reviewAt?: string }>>; overallStates?: Record<string, string>; targetDifficulties?: Record<string, Difficulty> };
type TargetConcept = { id: string; targetDifficulty?: Difficulty; curriculum?: { layer: Difficulty } | null };
export function targetDifficulty(concept: TargetConcept): Difficulty {
  return concept.curriculum?.layer || concept.targetDifficulty || "intermediate";
}
export function overallState(concept: TargetConcept, learner: LearnerState | null | undefined) {
  return learner?.overallStates?.[concept.id] || learner?.concepts[concept.id]?.[targetDifficulty(concept)]?.state || "unassessed";
}
export type Assessment = { correct: boolean; uncertain: boolean; hinted: boolean; notSure?: boolean; feedback: string; explanation: string;
  rubricScore?: number; partial?: boolean; contradiction?: boolean;
  confirmedWeakness?: boolean; evidenceOutcome?: string;
  rubricCoverage?: { criterionId: string; description: string; score: number; reason: string }[];
  misconceptions?: { description: string; responseQuote: string }[];
  timing?: { responseTimeMs: number | null; basis: string }; reasoning?: string | null;
};
export type LearningPlan = { version: number; goal: { description: string; conceptIds: string[] }; learnerVersion?: number;
  activityIds?: string[]; reviewDates?: Record<string, string>; stale?: boolean;
  selected?: { title: string; action: string; difficulty: Difficulty; objective: string } | null; reason?: string;
};
export type QuizTarget = { conceptId: string; title: string };
type Prerequisite = QuizTarget & { difficulty: Difficulty; state: string };
export type PrerequisiteBlock = {
  code: "unmet_prerequisites"; message: string; requested: QuizTarget;
  prerequisites: Prerequisite[]; nextStep: Prerequisite | null;
};
export class PrerequisiteBlockedError extends Error {
  constructor(readonly block: PrerequisiteBlock) { super(block.message); }
}
export type SavedMixedAnswer = { choiceIds?: string[]; blanks?: Record<string, string>; answerText?: string };
export type QuestionFormat = "multiple_answer" | "fill_in" | "open";
export type StudySession = { id: string; courseId: string; status: string; runIds: string[]; targetConceptId?: string | null; assessment: Assessment | null; selectedChoiceId?: string | null; notice?: string | null; plan?: LearningPlan;
  prerequisiteBlock?: PrerequisiteBlock;
  answer?: SavedMixedAnswer;
  activity: { id: string; conceptId: string; status: string; hintUsed: boolean; difficulty: string; prompt: string; choices: { id: string; text: string }[]; sources: Reference[]; action?: string; rationale?: string; objective?: string; extendedTopic?: boolean; extensionReason?: string | null; format?: QuestionFormat; blankIds?: string[] } | null };
export type RunSummary = { id: string; workflow: string; status: string; summary: string; startedAt?: string | null; documentId?: string | null; documentIds?: string[]; sessionId?: string | null; templateName?: string | null; model?: string | null; temperature?: number | null; modelsUsed?: string[]; stopSupported?: boolean; hierarchyMode?: "new" | "continue" | null; expertUsage?: { reportedCostUsd: number; reportedCalls: number; unreportedCalls: number; priorUsageUnknown: boolean } | null };
export type LearningMaterial = {
  curriculum?: CurriculumObjective | null;
  conceptId: string; documentId: string; filename: string; questionCount: number; sources: Reference[];
  questionCountsByDifficulty?: Record<Difficulty, number>;
  lessonsByDifficulty?: Partial<Record<Difficulty, LearningMaterial["lesson"]>>;
  sourcesByDifficulty?: Partial<Record<Difficulty, Reference[]>>;
  lesson: {
    title: string; objective: string; explanation: string;
    equations: { latex: string; explanation: string }[];
    workedExample: { title: string; steps: (string | { title: string; explanation: string; equations: string[] })[]; explanation: string };
    takeaway: string; commonMistake: string;
    flashcards: { front: string; back: string }[];
  };
};
export type LearningMaterials = { materials: LearningMaterial[]; expectedCount: number };
export function uploadCourseFile(courseId: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  form.append("defer_processing", "true");
  return api<{ documentId: string; duplicate: boolean }>(`courses/${encodeURIComponent(courseId)}/documents`, form);
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch(`/api/backend/${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: body === undefined || form ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (response.status === 409 && data?.detail?.code === "unmet_prerequisites") {
    throw new PrerequisiteBlockedError(data.detail);
  }
  if (!response.ok) {
    if (path === "evaluations/pseudo-runs/from-files" && response.status === 404 && data?.detail === "Not Found") {
      throw new Error("The learning server needs to be restarted to start tests from new course materials.");
    }
    const validation = Array.isArray(data?.detail) ? data.detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const field = (item.loc || []).filter((part) => part !== "body").join(".");
      return item.msg ? `${field ? `${field}: ` : ""}${item.msg}` : "";
    }).filter(Boolean).join("; ") : "";
    throw new Error(typeof data?.detail === "string" ? data.detail : validation || `Request failed (${response.status}). Please refresh and retry.`);
  }
  if (data == null) throw new Error("The learning server returned an unreadable response. Please refresh and retry.");
  return data as T;
}
