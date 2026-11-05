import { concepts, type Concept, type ConceptState } from "./demo-data";
import { practiceBank } from "./practice-bank";
import type { ConceptPractice, DemoAssessment } from "./practice-session";
export type { DemoAssessment } from "./practice-session";

export const difficulties = ["basic", "intermediate", "advanced"] as const;
export type Difficulty = (typeof difficulties)[number];
export const difficultyLabels: Record<Difficulty, string> = {
  basic: "Basic",
  intermediate: "Intermediate",
  advanced: "Advanced",
};
export type EvidenceSession = {
  independentQuestions?: number[];
  history?: DemoAssessment[];
  records?: Record<string, ConceptPractice>;
};
export type SourceReference = {
  id: string;
  lecture: "2" | "3";
  title: string;
  page: number;
  heading: string;
  excerpt: string;
  equation?: string;
};

const locations: Record<string, ["2" | "3", number]> = {
  vectors: ["2", 5],
  functions: ["2", 8],
  derivatives: ["2", 10],
  gradients: ["3", 9],
  chain: ["2", 14],
  descent: ["3", 12],
  rate: ["3", 13],
  backprop: ["3", 16],
  batches: ["3", 18],
  sgd: ["3", 21],
  momentum: ["3", 25],
  adam: ["3", 28],
};
// Illustrative references, not extracted or verified locations in the actual lecture PDFs.
export const conceptSources: Record<string, SourceReference> =
  Object.fromEntries(
    concepts.map((concept) => {
      const [lecture, page] = locations[concept.id];
      return [
        concept.id,
        {
          id: concept.id,
          lecture,
          page,
          title:
            lecture === "2"
              ? "Neural network foundations"
              : "Training & learning",
          heading: concept.title,
          excerpt:
            concept.id === "descent"
              ? "The gradient points in the direction of steepest local increase of the loss. Moving in the opposite direction can reduce the loss for a sufficiently small step. The learning rate controls the size of this step."
              : concept.summary,
          ...(concept.id === "descent"
            ? { equation: "θₜ₊₁ = θₜ − η ∇L(θₜ)" }
            : {}),
        },
      ];
    }),
  );

export const relatedConnections = [
  { from: "descent", to: "rate", label: "Step size controls the update" },
  {
    from: "backprop",
    to: "sgd",
    label: "Gradient computation and parameter updates",
  },
];

export function getConceptEvidence(concept: Concept, session: EvidenceSession) {
  const baseline = concepts.find((item) => item.id === concept.id)!;
  const record = session.records?.[concept.id];
  const history =
    record?.history ||
    (concept.id === "descent" && !session.records ? session.history || [] : []);
  const qualifying =
    record?.independentQuestions.length ??
    (concept.id === "descent" && !session.records
      ? session.independentQuestions?.length || 0
      : 0);
  const baselineIndependent = ["demonstrated", "review_due"].includes(
    baseline.state,
  )
    ? 2
    : 0;
  const independent =
    baselineIndependent +
    (record
      ? new Set(
          history
            .filter((item) => item.correct && !item.hinted)
            .map((item) => item.question),
        ).size
      : qualifying);
  const overall: ConceptState =
    record?.status ??
    (concept.id === "descent" && qualifying >= 2
      ? "demonstrated"
      : baseline.state);
  const basicKnown =
    ["demonstrated", "review_due"].includes(baseline.state) ||
    concept.id === "descent";
  const levels: Record<
    Difficulty,
    { state: ConceptState; independent: number; assisted: number }
  > = {
    basic: {
      state: basicKnown ? "demonstrated" : "unassessed",
      independent: basicKnown ? 2 : 0,
      assisted: 0,
    },
    intermediate: {
      state: overall,
      independent,
      assisted: history.filter((record) => record.correct && record.hinted)
        .length,
    },
    advanced: { state: "unassessed", independent: 0, assisted: 0 },
  };
  const reason = (level: Difficulty) => {
    const evidence = levels[level];
    if (evidence.state === "unassessed")
      return "There is not enough assessment evidence at this difficulty yet.";
    if (evidence.state === "review_due")
      return history.some((attempt) => !attempt.correct)
        ? "A later incorrect response conflicts with earlier evidence. Two new distinct independent checks are needed; previous history is retained."
        : "Two earlier independent responses are retained. The seven-day review date has passed in this sample history.";
    if (evidence.state === "demonstrated")
      return "Two distinct independent responses meet the sample criteria at this difficulty.";
    if (level === "intermediate" && qualifying === 1)
      return "One qualifying response is recorded. Another distinct independent question is needed.";
    if (evidence.assisted)
      return "A correct answer used a hint. More independent evidence is needed.";
    return "Earlier practice showed a gap. More independent evidence is needed at this difficulty.";
  };
  const latestIncorrect = [...history]
    .reverse()
    .find((attempt) => !attempt.correct);
  const misconception =
    overall !== "demonstrated" && latestIncorrect
      ? practiceBank[concept.id][latestIncorrect.question].choices.find(
          (choice) => choice.id === latestIncorrect.answer,
        )?.explanation
      : overall === "developing"
        ? (
            {
              descent:
                "A descent step does not necessarily make every parameter smaller.",
              rate: "A larger learning rate is not always a faster route to a lower loss.",
              sgd: "A mini-batch gradient is an estimate of the full-data gradient.",
            } as Record<string, string>
          )[concept.id]
        : undefined;
  return {
    overall,
    levels,
    reason,
    misconception,
    history,
    source: conceptSources[concept.id],
    target: "intermediate" as const,
    lastAssessed: history.length
      ? "This demo session"
      : baseline.state === "unassessed"
        ? "Not assessed"
        : baseline.state === "review_due"
          ? "8 Oct · sample history"
          : "16 Oct · sample history",
    review:
      overall === "review_due"
        ? history.some((attempt) => !attempt.correct)
          ? "Reassessment needed after conflicting evidence"
          : "Due 15 Oct · sample history"
        : overall === "demonstrated"
          ? history.length > 0
            ? "7 days after this demo assessment"
            : "Due 23 Oct · sample history"
          : "After understanding is demonstrated",
  };
}

export function getLearnerConcepts(session: EvidenceSession) {
  return concepts.map((concept) => ({
    ...concept,
    state: getConceptEvidence(concept, session).overall,
  }));
}

export function describeAttempt(record: DemoAssessment) {
  const question = practiceBank[record.conceptId || "descent"][record.question];
  return {
    question: question.prompt,
    answer:
      question.choices.find((choice) => choice.id === record.answer)?.text ||
      "No saved selection",
    explanation:
      question.choices.find((choice) => choice.id === record.answer)
        ?.explanation || "",
  };
}
