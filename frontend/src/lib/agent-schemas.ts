import type { WorkbenchAgent } from "./expert-templates";

export type AgentSchemaStage = {
  id: "analysis" | "lesson" | "questions";
  input: string[];
  inputExample?: Record<string, unknown>;
  inputNote?: string;
  outputSchema: string;
  output: string[];
};

export const agentSchemaContracts: Record<WorkbenchAgent, AgentSchemaStage[]> = {
  expert: [
    {
      id: "analysis",
      input: ["Section number and total", "Page numbers", "Passages with chunkId, page, and text"],
      inputExample: {
        section: 1,
        totalSections: 3,
        pages: [1],
        passages: [{ chunkId: "passage-id", page: 1, text: "Source passage text…" }],
      },
      outputSchema: "SectionGraph",
      output: ["concepts: id, title, summary, source citations, target difficulty", "prerequisites: supported links between concepts"],
    },
    {
      id: "lesson",
      input: ["Concept", "Relevant passages and primary passage IDs", "Curriculum objective and course catalog"],
      inputExample: {
        concept: { id: "concept-id", title: "Concept title", summary: "Grounded concept summary" },
        passages: [{ chunkId: "passage-id", page: 1, text: "Source passage text…" }],
        primaryPassageIds: ["passage-id"],
        curriculum: { conceptId: "concept-id", layer: "intermediate", teaches: "Objective…", assumes: [], adds: "Learning outcome…" },
        courseCatalog: [{ id: "concept-id", title: "Concept title", layer: "intermediate" }],
      },
      outputSchema: "PyramidMaterials",
      output: ["lesson: structured teaching content, worked example, flashcards, and citations", "tests: two basic questions with choices, answer keys, citations, and rubrics"],
    },
    {
      id: "questions",
      input: ["Concept and target difficulty", "Requested question format", "Relevant passages and previously used questions"],
      inputExample: {
        concept: { title: "Concept title", summary: "Grounded concept summary" },
        difficulty: "intermediate",
        previousPrompts: [],
        passages: [{ chunkId: "passage-id", text: "Source passage text…" }],
        format: "single_answer",
      },
      outputSchema: "Question format schema",
      output: ["Question for single answer, or OpenQuestion, MultipleAnswerQuestion, or FillInQuestion", "Prompt, answer data, explanations, citations, and rubric fields vary by format"],
    },
  ],
  tutor: [
    {
      id: "analysis",
      input: ["Learning goal", "Eligible activity candidates", "Learner memory for those candidates"],
      inputExample: {
        goal: { conceptId: "concept-id", description: "Learner goal" },
        candidates: [{ id: "candidate-id", conceptId: "concept-id", difficulty: "basic", action: "practice" }],
        learnerMemory: { "concept-id": { gap: null, confidence: 0.7 } },
      },
      outputSchema: "PlanChoice",
      output: ["candidateId: selected eligible action", "rationale: short explanation"],
    },
    {
      id: "lesson",
      input: ["Concept, public lesson, and current activity", "Learner message and conversation history", "Assessment-pending status and learner memory"],
      inputExample: {
        concept: { id: "concept-id", title: "Concept title" },
        lesson: { title: "Lesson title", explanation: "Public lesson content…" },
        activity: { prompt: "Current question…", choices: [] },
        assessment_pending: false,
        history: [{ role: "user", text: "Learner message…" }],
        message: "Learner message…",
        learnerMemory: { evidence: "summary of relevant learner evidence" },
      },
      outputSchema: "TutorChatReply",
      output: ["text: tutor response", "observation: optional strength or gap with a supporting quote"],
    },
    {
      id: "questions",
      input: ["Selected concept and difficulty", "Eligible question bank and prior activity history", "Requested format when mixed formats are enabled"],
      inputNote: "No model input object is used for selection. If the runtime needs a new question, it assembles the Expert question-generation payload shown in that agent’s Question generation stage.",
      outputSchema: "Runtime-selected activity",
      output: ["The runtime selects an eligible saved question; no separate model selection schema is used", "If a new question is needed, the Expert uses a format-specific question schema"],
    },
  ],
  assessing: [
    {
      id: "analysis",
      input: ["Question, learner response, and correctness from the server-held answer key", "Hint use, reasoning, timing, and prior evidence", "Rubric, answer key, and supporting passages"],
      inputExample: {
        question: { prompt: "Question text…", choices: [{ id: "a", text: "Option A" }] },
        selectedChoiceId: "a",
        correct: true,
        hintUsed: false,
        answerExplanation: "Private answer explanation…",
        reasoning: null,
        timing: { responseTimeMs: 12000, basis: "client" },
        priorEvidence: {},
        previousAssessments: [],
        passages: [{ chunkId: "passage-id", text: "Source passage text…" }],
        difficulty: "basic",
        rubric: [],
        referenceAnswer: "Reference answer…",
      },
      outputSchema: "Assessment",
      output: ["feedback and uncertainty", "coverage by rubric criterion and cited misconceptions", "contradiction flag for conflicting evidence"],
    },
    {
      id: "lesson",
      input: ["Same reviewed response and rubric context as answer analysis"],
      inputNote: "Feedback is returned inside the Assessment object from answer analysis; production does not make a separate feedback call.",
      outputSchema: "Assessment.feedback",
      output: ["Feedback is a field in the Assessment response, not a separate production model call"],
    },
    {
      id: "questions",
      input: ["Validated assessment and current learner evidence"],
      inputNote: "The runtime updates learner evidence from the validated assessment. It does not assemble a separate model input object for this stage.",
      outputSchema: "Backend evidence update",
      output: ["The runtime derives and records the learner evidence transition; this stage has no separate model output schema"],
    },
  ],
};
