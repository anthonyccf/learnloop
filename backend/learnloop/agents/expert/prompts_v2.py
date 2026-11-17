"""Expert prompt version 2, selected with PROMPT_VERSION=v2.

Course organization, curriculum and relationship prompts are unchanged and stay in prompts.py.
"""

DIFFICULTY_LEVELS = """
Difficulty levels:
- basic: recall or directly explain one idea as taught (define, identify, state, recognize).
- intermediate: apply or compare ideas in a new but familiar case (calculate, predict, contrast, explain why).
- advanced: analyze, diagnose or judge a situation that combines several ideas (evaluate a trade-off,
  find an error, choose and justify an approach).
Difficulty comes from the reasoning required, never from harder vocabulary, obscure details or invented facts.
"""

MCQ_QUALITY = """
Multiple-choice quality:
- The stem asks one clear question that could be answered before reading the options.
- Exactly one option is correct. Each distractor reflects a specific, plausible misconception about this topic.
- Keep all options similar in length, grammar and detail so the correct one does not stand out.
- Do not use "all of the above", "none of the above", double negatives or trick wording.
- Do not echo distinctive stem wording only in the correct option.
- The hint points to the relevant idea without revealing or ruling out any option.
- The explanation says why the correct option is right and why each distractor is wrong.
"""

MCQ_RUBRIC = """
Private rubric for every multiple-choice question:
- referenceAnswer: a short model explanation of the correct answer.
- rubric: 1-5 criteria. Each has a distinct lowercase id, a description of one piece of understanding,
  an integer weight 1-5, 1-4 supporting sources, and choiceScores for a, b, c and d in [0, 1].
- The correct option scores 1 on every criterion. Every wrong option scores below 1 on at least one criterion.
- Give a wrong option partial credit only for understanding its own text actually expresses.
  Choosing an option never demonstrates a written explanation.
"""

EXAMPLE_STYLE_PROMPT = """
Worked example rules:
- Write 2-8 small steps. Each step has a short title, one plain sentence on WHY the step is needed,
  and an equations array with at most three raw LaTeX strings without delimiters.
- For a calculation, the first step states the given values and the goal. Then use one step per calculated
  quantity: the symbolic formula, then the substituted numbers, then the simplified result, each on its own
  equation line. Do not merge unrelated calculations to save steps.
- Keep every intermediate value, unit, rounding and clipping decision. For rounding, show the value before
  and after. For clipping, state whether the bounds change the result and why.
- For a conceptual example, use short reasoning steps with empty equations arrays. Never invent a formula.
- LaTeX escaping: each decoded command has a single backslash. In JSON, write "\\\\frac{a}{b}" so it
  decodes to \\frac{a}{b}. Use \\text{...} for word labels in subscripts and for upright units.
- In prose fields, write math inline as \\( ... \\).
- The explanation field states in one or two sentences what the result means.
- Label invented numbers "Hypothetical example". Keep supported assumptions, and never present invented
  numbers as reported measurements. Do not include test answer keys.
"""

POST_STYLE_PROMPT = (
    """
Write a short, standalone learning post for ONE concept.

Voice:
- Everyday English for a learner who already knows the listed prerequisites. Explain only new technical terms.
- One idea per sentence, usually 8-14 words. Vary sentence openings. Use "because" and "so" to show reasoning.
- The post must stand alone: never mention "the lecture", "the slide" or "the PDF".

Fields:
- title: short and specific.
- objective: one sentence saying what the learner will be able to do.
- hook: one sentence with a familiar problem or useful observation.
- points: 3-6 items of one or two sentences, each teaching or connecting one idea. A point may start with
  a short **bold label**. The hook and points together are roughly 70-130 words; cut filler, recaps and
  unrelated background, but keep necessary reasoning.
- equations: 0-2 source-supported formulas, each with an explanation that defines every symbol. Leave the
  array empty when no formula is needed; never add decorative formulas.
- workedExample: one example following the worked example rules below. It is not counted in the word budget.
  Do not repeat it in the points, and keep a calculation complete rather than cutting steps.
- takeaway: one sentence on why the idea matters.
- commonMistake: one specific mistake learners make, and why it is wrong.
- flashcards: 1-2 cards. The front asks a question; the back explains the answer.
- sources: chunkIds of supporting passages, copied exactly as supplied.

Math formatting:
- In every text field, wrap variables, subscripts and powers in \\( ... \\): write \\(x_i\\), \\(x^2\\)
  and \\(t_{\\text{before}}\\), never bare x_i, x^2 or t_before.
- Use braces for multi-character subscripts or exponents, and \\text{...} for word labels.

Evidence:
- Use only the supplied passages as factual evidence. Faithful paraphrase is fine. A separate review checks
  every substantive claim and citation against its passage before learners see it.
"""
    + EXAMPLE_STYLE_PROMPT
)

PYRAMID_MATERIALS_PROMPT = (
    POST_STYLE_PROMPT
    + """
Task: write ONE primary lesson at curriculum.layer, and exactly two Basic starter questions.

Inputs:
- concept: the concept to teach.
- curriculum: this lesson's plan. layer is basic, intermediate or advanced; teaches is its exclusive scope;
  adds is the new capability beyond its prerequisites; assumes lists prerequisites already learned.
- courseCatalog: scopes owned by other lessons.
- passages: the only allowed factual evidence, each with chunkId, page and text.
- primaryPassageIds: the reviewed anchor passages for this objective. Prefer them for factual claims.
- sourceReviewFeedback, rejectedDraft, revisionInstruction (optional): a previous draft failed review.
  Fix every reported issue. Do not keep its faulty claims or citations.

Lesson scope:
- Teach exactly curriculum.teaches so the learner gains curriculum.adds.
- basic: one focused foundation. intermediate: connect and apply foundations. advanced: integrate
  applications to analyze or judge.
- Treat curriculum.assumes as learned; a one-sentence reminder is allowed. Do not reteach any scope in
  courseCatalog or reuse its definitions, explanations or worked examples.
- Some passages contain exercises, misconceptions or earlier example drafts. Do not blend conflicting
  examples unless a passage connects them.
- Never raise the level with harder vocabulary or invented facts.

Starter questions (tests):
- Exactly two distinct four-option single-answer questions, both with difficulty "basic", testing recall
  or direct understanding of this objective. This holds whatever the lesson layer is.
- Keep each question's answer, explanation, hint and rubric inside the question. The lesson must not
  contain an answer key.
"""
    + MCQ_QUALITY
    + MCQ_RUBRIC
    + "\nReturn only lesson and tests.\n"
)

EXPERT_MATERIALS_PROMPT = (
    POST_STYLE_PROMPT
    + """
Task: write three lessons for ONE concept, one per difficulty, and exactly six practice questions.

Inputs:
- concept: the concept to teach, with its title, summary and sources.
- passages: the only allowed factual evidence, each with chunkId and text.

Lessons, each using the post structure above with its own objective, worked example and sources:
- basicLesson: direct understanding of the core idea.
- lesson: the Intermediate lesson, applying or comparing the idea.
- advancedLesson: analysis of supported comparisons or multi-step reasoning.
Each lesson adds something the previous level did not; do not restate the same post three times.
Never raise a level with outside facts or harder vocabulary. Lessons must not contain answer keys.

Questions (tests):
- Exactly six distinct four-option single-answer questions: two basic, two intermediate and two advanced,
  with the difficulty field set accordingly.
- Each question tests a different aspect or application of this concept and cites its supporting passages.
- Keep each question's answer, explanation, hint and rubric inside the question.
"""
    + DIFFICULTY_LEVELS
    + MCQ_QUALITY
    + MCQ_RUBRIC
)

ON_DEMAND_QUESTION_PROMPT = (
    """
Write one new four-option, single-answer practice question about the concept at the requested difficulty.

Inputs:
- concept: title and summary of the concept to test.
- difficulty: the exact value for the difficulty field.
- previousPrompts: questions the learner has already seen. Test a different aspect, case or set of numbers;
  do not paraphrase them.
- passages: the only allowed evidence for the question, correct answer, hint, explanation and rubric.
- diagnosticFocus (optional): a suspected skill gap. Probe it with a fresh example. Never quote or identify
  the learner.
- reviewFeedback (optional): why the previous attempt was rejected. Fix that issue with the available passages.
"""
    + DIFFICULTY_LEVELS
    + MCQ_QUALITY
    + MCQ_RUBRIC
)

QUESTION_KEY_PROMPT = """
Independently answer each multiple-choice question using only that question's passages.
- Check every option against the passages before choosing.
- Return one answer per question, in input order: the option ID the passages support as the single
  correct answer.
- Return "uncertain" when the passages support no option, support more than one, or the answer needs
  outside knowledge.
- Do not guess from general knowledge or from how the options are worded.
"""

FORMAT_INSTRUCTIONS = {
    "multiple_answer": (
        "Write four options with two or three correct answers. Map each correct option exactly once using "
        "choiceIds on its rubric criterion; each criterion needs at least one choiceId. Do not map distractors. "
        "Each distractor reflects a specific misconception, and all options are similar in length and detail."
    ),
    "fill_in": (
        "Mark each blank as [[id]] and use one rubric criterion per blank ID. List accepted equivalents "
        "(synonyms, notation, numeric forms) for each blank. State the required units and precision in the prompt."
    ),
    "open": (
        "Ask a short question that one to four sentences can answer. Supply a reference answer and source-backed "
        "criteria that accept valid alternative wording or reasoning. Give each independently meaningful part of "
        "the answer its own weighted criterion. A criterion that needs a relationship, such as a cause, comparison "
        "or consequence, must say so; naming the related terms alone does not meet it. Describe what each "
        "criterion requires so partial understanding can be scored. Avoid artificial criteria."
    ),
}

MIXED_PROMPT = (
    """
Write one new question about the concept in the requested format and difficulty.

Inputs:
- concept, difficulty, previousPrompts, passages, diagnosticFocus and reviewFeedback: as for any practice
  question. Use only the passages as evidence, set difficulty to the exact requested value, avoid repeating
  previousPrompts, probe diagnosticFocus with a fresh example without quoting the learner, and fix any
  reviewFeedback.
- format and formatInstructions: the question format and its rules. Follow formatInstructions exactly.

Provide the prompt, a private explanation, a hint that points to the relevant idea without giving the
answer, a referenceAnswer, and a weighted rubric whose every criterion cites supporting passages.
"""
    + DIFFICULTY_LEVELS
)

SOLVE_PROMPT = """
Independently solve the question using only the supplied passages. You have not seen the answer key.
Answer in the field that matches the question format and leave the other fields empty:
- multiple_answer: choiceIds with every correct option and no others.
- fill_in: one entry in blanks for every blank ID, in the units and precision the prompt asks for.
- open: answerText with a short answer whose reasoning the passages support.
Set uncertain to true when the passages are incomplete, a closed-format question has more than one
defensible answer, or answering needs outside knowledge.
"""
