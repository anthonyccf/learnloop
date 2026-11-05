import { concepts, type ConceptState, type Concept } from "./demo-data";
import { practiceBank } from "./practice-bank";

export type DemoAssessment = {
  id: string;
  conceptId: string;
  question: number;
  answer: string;
  correct: boolean;
  hinted: boolean;
  at: string;
};
export type ConceptPractice = {
  answer: string;
  question: number;
  hinted: boolean;
  independentQuestions: number[];
  attempts: number;
  feedback: string;
  history: DemoAssessment[];
  status: ConceptState;
  sessionBefore: ConceptState;
  sessionStart: number;
  ended: boolean;
};
export type PracticeSnapshot = {
  conceptId: string;
  records: Record<string, ConceptPractice>;
  loaded: boolean;
};
export type PracticeAction =
  | { type: "load"; value: PracticeSnapshot }
  | { type: "activate"; conceptId: string }
  | { type: "answer"; value: string }
  | { type: "hint" }
  | { type: "submit"; at: string }
  | { type: "next" }
  | { type: "end" }
  | { type: "restart" }
  | { type: "reset" };
export const isConcept = (id: string) =>
  concepts.some((concept) => concept.id === id);
export function createRecord(id: string): ConceptPractice {
  const status = concepts.find((concept) => concept.id === id)!.state;
  return {
    answer: "",
    question: 0,
    hinted: false,
    independentQuestions: [],
    attempts: 0,
    feedback: "",
    history: [],
    status,
    sessionBefore: status,
    sessionStart: 0,
    ended: false,
  };
}
export function initialPractice(): PracticeSnapshot {
  return {
    conceptId: "descent",
    records: { descent: createRecord("descent") },
    loaded: false,
  };
}
export function conceptStatus(
  id: string,
  records: PracticeSnapshot["records"],
): ConceptState {
  return (
    records[id]?.status || concepts.find((concept) => concept.id === id)!.state
  );
}
export function unmetPrerequisites(
  id: string,
  records: PracticeSnapshot["records"],
) {
  return concepts
    .find((concept) => concept.id === id)!
    .prerequisites.filter(
      (parent) => conceptStatus(parent, records) !== "demonstrated",
    );
}
export function sessionAttempts(record: ConceptPractice) {
  return record.history.slice(record.sessionStart);
}
export function sessionIndependent(record: ConceptPractice) {
  return new Set(
    sessionAttempts(record)
      .filter((attempt) => attempt.correct && !attempt.hinted)
      .map((attempt) => attempt.question),
  ).size;
}

export function practiceReducer(
  state: PracticeSnapshot,
  action: PracticeAction,
): PracticeSnapshot {
  if (action.type === "load") return { ...action.value, loaded: true };
  if (action.type === "reset") return { ...initialPractice(), loaded: true };
  if (!state.loaded) return state;
  if (action.type === "activate")
    return isConcept(action.conceptId)
      ? {
          ...state,
          conceptId: action.conceptId,
          records: {
            ...state.records,
            [action.conceptId]:
              state.records[action.conceptId] || createRecord(action.conceptId),
          },
        }
      : state;
  const record = state.records[state.conceptId];
  const save = (next: ConceptPractice) => ({
    ...state,
    records: { ...state.records, [state.conceptId]: next },
  });
  if (action.type === "end") return save({ ...record, ended: true });
  if (unmetPrerequisites(state.conceptId, state.records).length) return state;
  if (action.type === "restart")
    return save({
      ...record,
      answer: "",
      question: 0,
      hinted: false,
      feedback: "",
      sessionBefore: record.status,
      sessionStart: record.history.length,
      ended: false,
    });
  if (record.ended) return state;
  if (action.type === "answer")
    return record.feedback ? state : save({ ...record, answer: action.value });
  if (action.type === "hint")
    return record.feedback ? state : save({ ...record, hinted: true });
  if (action.type === "next")
    return record.feedback
      ? save({
          ...record,
          answer: "",
          question:
            (record.question + 1) % practiceBank[state.conceptId].length,
          hinted: false,
          feedback: "",
        })
      : state;
  const question = practiceBank[state.conceptId][record.question];
  if (
    record.feedback ||
    !question.choices.some((choice) => choice.id === record.answer) ||
    !Number.isFinite(Date.parse(action.at))
  )
    return state;
  const correct = record.answer === question.correctId;
  const independentQuestions = !correct
    ? []
    : !record.hinted
      ? [...new Set([...record.independentQuestions, record.question])]
      : record.independentQuestions;
  const status: ConceptState = !correct
    ? record.status === "demonstrated" || record.status === "review_due"
      ? "review_due"
      : "developing"
    : independentQuestions.length >= 2
      ? "demonstrated"
      : record.status === "demonstrated" || record.status === "review_due"
        ? record.status
        : "developing";
  return save({
    ...record,
    independentQuestions,
    status,
    attempts: record.attempts + 1,
    feedback: correct ? (record.hinted ? "assisted" : "success") : "practice",
    history: [
      ...record.history,
      {
        id: `${state.conceptId}-${record.attempts + 1}`,
        conceptId: state.conceptId,
        question: record.question,
        answer: record.answer,
        correct,
        hinted: record.hinted,
        at: action.at,
      },
    ],
  });
}

export function recommendedConcept(
  id: string,
  records: PracticeSnapshot["records"],
): Concept | null {
  const unmet = unmetPrerequisites(id, records);
  if (unmet.length) return recommendedConcept(unmet[0], records);
  if (conceptStatus(id, records) !== "demonstrated")
    return concepts.find((concept) => concept.id === id)!;
  const eligible = concepts.filter(
    (concept) =>
      concept.id !== id &&
      conceptStatus(concept.id, records) !== "demonstrated" &&
      !unmetPrerequisites(concept.id, records).length,
  );
  return (
    eligible.find((concept) => concept.prerequisites.includes(id)) ||
    eligible.find(
      (concept) => conceptStatus(concept.id, records) === "review_due",
    ) ||
    eligible[0] ||
    null
  );
}

function object(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
const states = ["unassessed", "developing", "demonstrated", "review_due"];
export function restorePractice(value: unknown): PracticeSnapshot | null {
  if (
    !object(value) ||
    typeof value.conceptId !== "string" ||
    !isConcept(value.conceptId) ||
    !object(value.records)
  )
    return null;
  for (const [id, record] of Object.entries(value.records)) {
    if (
      !isConcept(id) ||
      !object(record) ||
      !Number.isInteger(record.question) ||
      Number(record.question) < 0 ||
      Number(record.question) >= practiceBank[id].length ||
      typeof record.answer !== "string" ||
      (record.answer !== "" &&
        !practiceBank[id][Number(record.question)].choices.some(
          (choice) => choice.id === record.answer,
        )) ||
      typeof record.hinted !== "boolean" ||
      !Array.isArray(record.independentQuestions) ||
      record.independentQuestions.some(
        (index) =>
          !Number.isInteger(index) ||
          index < 0 ||
          index >= practiceBank[id].length,
      ) ||
      new Set(record.independentQuestions).size !==
        record.independentQuestions.length ||
      !Number.isInteger(record.attempts) ||
      Number(record.attempts) < 0 ||
      !["", "success", "assisted", "practice"].includes(
        String(record.feedback),
      ) ||
      !states.includes(String(record.status)) ||
      !states.includes(String(record.sessionBefore)) ||
      typeof record.ended !== "boolean" ||
      !Array.isArray(record.history) ||
      !Number.isInteger(record.sessionStart) ||
      Number(record.sessionStart) < 0 ||
      Number(record.sessionStart) > record.history.length
    )
      return null;
    for (const attempt of record.history) {
      if (
        !object(attempt) ||
        attempt.conceptId !== id ||
        typeof attempt.id !== "string" ||
        !Number.isInteger(attempt.question) ||
        Number(attempt.question) < 0 ||
        Number(attempt.question) >= practiceBank[id].length ||
        !practiceBank[id][Number(attempt.question)].choices.some(
          (choice) => choice.id === attempt.answer,
        ) ||
        attempt.correct !==
          (attempt.answer ===
            practiceBank[id][Number(attempt.question)].correctId) ||
        typeof attempt.hinted !== "boolean" ||
        typeof attempt.at !== "string" ||
        !Number.isFinite(Date.parse(attempt.at))
      )
        return null;
    }
    if (Number(record.attempts) < record.history.length) return null;
  }
  if (!value.records[value.conceptId]) return null;
  return { ...value, loaded: true } as PracticeSnapshot;
}

export function migrateDescent(value: unknown): PracticeSnapshot | null {
  if (!object(value) || !Array.isArray(value.independentQuestions)) return null;
  const record = { ...createRecord("descent"), ...value };
  record.status =
    Array.isArray(value.independentQuestions) &&
    value.independentQuestions.length >= 2
      ? "demonstrated"
      : "developing";
  record.sessionBefore = record.status;
  record.history = Array.isArray(value.history)
    ? value.history.map((attempt) => ({ ...attempt, conceptId: "descent" }))
    : [];
  record.sessionStart = record.history.length;
  record.ended =
    record.feedback === "success" && record.independentQuestions.length >= 2;
  return restorePractice({
    conceptId: "descent",
    records: { descent: record },
  });
}
