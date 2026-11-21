"""Deliberately simple workflow fixtures. Not a research simulator or question bank."""

from learnloop.agents.assessing.mixed_answers import BlankEquivalence
from learnloop.core.schemas import (
    Assessment,
    DifficultyMaterials,
    ExpertSolution,
    ExtendedTopicReview,
    FillInQuestion,
    Graph,
    GroundingReview,
    MultipleAnswerQuestion,
    OpenQuestion,
    PlanChoice,
    PostLesson,
    QuestionKeyCheck,
    WorkbenchDecision,
    WorkbenchTutorReply,
)
from learnloop.evaluation.artifacts import freeze
from learnloop.evaluation.belief_student import (
    BeliefAnswer,
    BeliefUpdate,
    InitialMisconception,
    MixedBeliefAnswer,
)
from learnloop.evaluation.prepare import build_expert, validate_exams
from learnloop.evaluation.provider import BudgetExhausted
from learnloop.evaluation.schema import (
    EXPERTS,
    ExamDraft,
    LearningUpdate,
    MixedStudentReply,
    StudentReply,
)


def question(concept, source, level, label):
    statement = source["text"][:180]
    return {
        "difficulty": level,
        "prompt": f"Workflow fixture {label}: {concept['title']} ({level}). Which claim is supported?",
        "choices": [
            {"id": k, "text": v}
            for k, v in zip(
                "abcd",
                [
                    f"Supported source claim: {statement}",
                    "The source supports no claims.",
                    "All methods have identical behavior.",
                    "Evidence never affects this concept.",
                ],
            )
        ],
        "correctChoiceId": "a",
        "explanation": "The supplied passage states the supported claim.",
        "hint": "Look for a claim supported by the source.",
        "sources": [{"chunkId": source["chunkId"], "quote": source["text"][:100]}],
        "referenceAnswer": f"The supported claim is: {statement}",
        "rubric": [
            {
                "id": "claim",
                "description": "Recognize the claim supported by the supplied passage.",
                "weight": 1,
                "choiceScores": {"a": 1, "b": 0, "c": 0, "d": 0},
                "sources": [{"chunkId": source["chunkId"], "quote": source["text"][:100]}],
            }
        ],
    }


class FixtureProvider:
    offline = True
    model = "workflow-fixture"
    temperature, seed = 0.2, 72

    def __init__(self):
        self.calls = []
        self.max_calls = 100000

    def partition(self, name, parts):
        return FixtureProvider()

    def generate(self, role, instruction, context, output):
        if len(self.calls) >= self.max_calls:
            raise BudgetExhausted("Offline fixture call limit reached")
        self.calls.append(
            {
                "role": role,
                "schema": output.__name__,
                "inputTokens": 0,
                "outputTokens": 0,
                "costUsd": 0,
                "latencyMs": 0,
                "status": "completed",
                "model": self.model,
            }
        )
        if output is Graph:
            return Graph(
                concepts=context["concepts"],
                prerequisites=context.get("referencePrerequisites", []),
            )
        if output is GroundingReview:
            return GroundingReview(
                status="supported", summary="Synthetic fixture receipt, not semantic verification."
            )
        if output is DifficultyMaterials:
            concept, source = context["concept"], context["passages"][0]
            lesson = {
                "title": concept["title"],
                "objective": concept["summary"][:160],
                "hook": "Read this supplied claim and connect it to the course.",
                "points": [
                    concept["summary"][:180],
                    "Use source evidence when applying this idea.",
                    "Compare the supported claim with common mistakes.",
                ],
                "equations": [],
                "workedExample": {
                    "title": "Source-supported conceptual example",
                    "steps": [
                        {
                            "title": "Read the claim",
                            "explanation": "Identify the claim in the supplied passage.",
                            "equations": [],
                        },
                        {
                            "title": "Check the evidence",
                            "explanation": "Compare the claim with the same source passage.",
                            "equations": [],
                        },
                    ],
                    "explanation": "The source provides evidence for the claim.",
                },
                "takeaway": "Use the source evidence to justify the claim.",
                "commonMistake": "Treating an unsupported claim as an established fact.",
                "flashcards": [
                    {
                        "front": "What supports this claim?",
                        "back": "The supplied course passage supports this claim.",
                    }
                ],
                "sources": [{"chunkId": source["chunkId"], "quote": source["text"][:100]}],
            }
            return DifficultyMaterials(
                lesson=lesson,
                basicLesson=lesson,
                advancedLesson=lesson,
                tests=[
                    question(concept, source, level, f"train-{i}")
                    for level in ("basic", "intermediate", "advanced")
                    for i in range(2)
                ],
            )
        if output is ExamDraft:
            return ExamDraft(
                **{
                    phase: [
                        question(context["concept"], context["passages"][0], level, phase)
                        for level in ("basic", "intermediate", "advanced")
                    ]
                    for phase in ("pre", "post")
                }
            )
        if output is PlanChoice:
            return PlanChoice(
                candidateId=context["candidates"][0]["id"],
                rationale="Workflow fixture selects the leading eligible candidate.",
            )
        if output is StudentReply:
            return StudentReply(
                choiceId="a" if context["canAnswerIndependently"] else "b",
                reasoning="The source supports the selected claim."
                if context["canAnswerIndependently"]
                else "I am missing some understanding.",
                hintRequested=context["requestHint"],
                memoryUpdate="Remember the supported source claim." if context["teaching"] else "",
                learningGain=0.1 if context["teaching"] else 0,
            )
        if output is MixedStudentReply:
            q = context["question"]
            kind = q.get("format", "single_answer")
            can = context["canAnswerIndependently"]
            return MixedStudentReply(
                choiceIds=(["a", "b"] if can else ["c"]) if kind == "multiple_answer" else [],
                blanks=[
                    {"id": blank_id, "text": "gradient" if can else "wrong-term"}
                    for blank_id in q.get("blankIds", [])
                ]
                if kind == "fill_in"
                else [],
                answerText=(
                    "Subtract the gradient to reduce the loss." if can else "Increase the loss."
                )
                if kind == "open"
                else "",
                reasoning="The source supports the selected claim."
                if can
                else "I am missing some understanding.",
                hintRequested=context["requestHint"],
                memoryUpdate="Remember the supported source claim." if context["teaching"] else "",
                learningGain=0.1 if context["teaching"] else 0,
            )
        if output is InitialMisconception:
            return InitialMisconception(belief="I think all methods give identical results.")
        if output is BeliefAnswer:
            beliefs = context["recalledBeliefs"]
            return BeliefAnswer(
                choiceId="a" if beliefs else "b",
                uncertain=not beliefs,
                reasoning=beliefs[0][:600] if beliefs else "I am unsure.",
            )
        if output is MixedBeliefAnswer:
            q = context["question"]
            kind = q.get("format", "single_answer")
            beliefs = context["recalledBeliefs"]
            return MixedBeliefAnswer(
                choiceIds=(["a", "b"] if beliefs else ["c"]) if kind == "multiple_answer" else [],
                blanks=[
                    {"id": blank_id, "text": "gradient" if beliefs else "unsure"}
                    for blank_id in q.get("blankIds", [])
                ]
                if kind == "fill_in"
                else [],
                answerText=(beliefs[0][:400] if beliefs else "I am unsure.")
                if kind == "open"
                else "",
                uncertain=not beliefs,
                reasoning=beliefs[0][:600] if beliefs else "I am unsure.",
            )
        if output is BeliefUpdate:
            claim = context["deliveredText"][0][:400]
            return BeliefUpdate(
                revisions=[{"belief": claim, "evidenceQuote": claim, "replaces": None}]
            )
        if output is LearningUpdate:
            return LearningUpdate(
                memoryUpdate="Remember the claim explained in the delivered feedback.",
                learningGain=0.08,
                misconceptionResolved=True,
            )
        if output is Assessment:
            selected = context.get("selectedChoiceId")
            quote = (context.get("answerText") or context.get("reasoning") or "")[:600]
            coverage = []
            for criterion in context.get("rubric") or []:
                scores = criterion.get("choiceScores") or {}
                score = scores[selected] if selected in scores else 1
                coverage.append(
                    {
                        "criterionId": criterion["id"],
                        "score": score,
                        "reason": "Controlled criterion coverage.",
                        "responseQuote": quote,
                    }
                )
            return Assessment(
                feedback="Controlled workflow feedback only.",
                uncertain=False,
                coverage=coverage,
                misconceptions=[],
                contradiction=False,
            )
        if output is PostLesson:
            return fixture_post_lesson(context)
        if output is WorkbenchDecision:
            return WorkbenchDecision(
                action="lesson", reason="A lesson fits the learner's current evidence."
            )
        if output is WorkbenchTutorReply:
            return WorkbenchTutorReply(
                text="Look at how the supplied source describes the update.",
                observation=None,
                nextAction="quiz",
            )
        if output is MultipleAnswerQuestion:
            return fixture_multiple_answer(context)
        if output is FillInQuestion:
            return fixture_fill_in(context)
        if output is OpenQuestion:
            return fixture_open_question(context)
        if output is ExpertSolution:
            kind = context.get("format")
            if kind == "fill_in":
                return ExpertSolution(
                    uncertain=False,
                    blanks=[
                        {"id": blank_id, "text": "gradient"}
                        for blank_id in context.get("blankIds") or ["term"]
                    ],
                )
            if kind == "multiple_answer":
                return ExpertSolution(uncertain=False, choiceIds=["a", "b"])
            return ExpertSolution(
                uncertain=False, answerText="Subtract the gradient to reduce the loss."
            )
        if output is BlankEquivalence:
            return BlankEquivalence(possibleEquivalence=False)
        if output is QuestionKeyCheck:
            return QuestionKeyCheck(answers=["a"] * len(context["questions"]))
        if output is ExtendedTopicReview:
            return ExtendedTopicReview(
                approved=False, reason="The fixture question stays within the supplied source."
            )
        raise ValueError(f"Unsupported fixture output: {output.__name__}")


def fixture_source(context):
    source = context["passages"][0]
    return source["chunkId"], source["text"][:100]


def fixture_post_lesson(context):
    concept = context.get("concept") or {}
    chunk_id, quote = fixture_source(context)
    return PostLesson.model_validate(
        {
            "title": concept.get("title") or "Course lesson",
            "objective": (concept.get("summary") or "Use the supplied course passage.")[:180],
            "hook": "Read this supplied claim and connect it to the course.",
            "points": [
                "Use the supplied passage as the source for this idea.",
                "Compare the supported claim with an unsupported alternative.",
                "Apply the claim only where the passage gives evidence.",
            ],
            "equations": [],
            "workedExample": {
                "title": "Source-supported conceptual example",
                "steps": [
                    {
                        "title": "Read the claim",
                        "explanation": "Identify the claim in the supplied passage.",
                        "equations": [],
                    },
                    {
                        "title": "Check the evidence",
                        "explanation": "Compare the claim with the same source passage.",
                        "equations": [],
                    },
                ],
                "explanation": "The source provides evidence for the claim.",
            },
            "takeaway": "Use the source evidence to justify the claim.",
            "commonMistake": "Treating an unsupported claim as an established fact.",
            "flashcards": [
                {
                    "front": "What supports this claim?",
                    "back": "The supplied course passage supports this claim.",
                }
            ],
            "sources": [{"chunkId": chunk_id, "quote": quote}],
        }
    )


def fixture_multiple_answer(context):
    chunk_id, quote = fixture_source(context)
    label = len(context.get("previousPrompts") or [])
    source = {"chunkId": chunk_id, "quote": quote}
    return MultipleAnswerQuestion.model_validate(
        {
            "difficulty": context["difficulty"],
            "prompt": f"Workflow fixture multi {label}: which claims does the source support?",
            "choices": [
                {"id": "a", "text": f"Supported source claim: {quote}"},
                {"id": "b", "text": "The passage gives evidence for this idea."},
                {"id": "c", "text": "The source supports no claims."},
                {"id": "d", "text": "Evidence never affects this concept."},
            ],
            "correctChoiceIds": ["a", "b"],
            "explanation": "The supplied passage states the supported claims.",
            "hint": "Look for a claim supported by the source.",
            "sources": [source],
            "referenceAnswer": "The supported claims are the source-backed options.",
            "rubric": [
                {
                    "id": "first",
                    "description": "Recognize the first supported claim.",
                    "weight": 1,
                    "choiceIds": ["a"],
                    "sources": [source],
                },
                {
                    "id": "second",
                    "description": "Recognize the second supported claim.",
                    "weight": 1,
                    "choiceIds": ["b"],
                    "sources": [source],
                },
            ],
        }
    )


def fixture_fill_in(context):
    chunk_id, quote = fixture_source(context)
    label = len(context.get("previousPrompts") or [])
    source = {"chunkId": chunk_id, "quote": quote}
    return FillInQuestion.model_validate(
        {
            "difficulty": context["difficulty"],
            "prompt": f"Workflow fixture blank {label}: the update subtracts the [[term]].",
            "blanks": [{"id": "term", "acceptedAnswers": ["gradient"], "caseSensitive": False}],
            "explanation": "The supplied passage names the quantity in the update.",
            "hint": "Use the quantity named by the source.",
            "sources": [source],
            "referenceAnswer": "The missing term is gradient.",
            "rubric": [
                {
                    "id": "term",
                    "description": "Name the quantity being subtracted.",
                    "weight": 1,
                    "sources": [source],
                }
            ],
        }
    )


def fixture_open_question(context):
    chunk_id, quote = fixture_source(context)
    label = len(context.get("previousPrompts") or [])
    source = {"chunkId": chunk_id, "quote": quote}
    return OpenQuestion.model_validate(
        {
            "difficulty": context["difficulty"],
            "prompt": f"Workflow fixture open {label}: explain the supported update.",
            "explanation": "Subtract the gradient to reduce the loss.",
            "hint": "Use the source description of the update.",
            "sources": [source],
            "referenceAnswer": "Subtract the gradient to reduce the loss.",
            "rubric": [
                {
                    "id": "direction",
                    "description": "Describe the update that reduces the loss.",
                    "weight": 1,
                    "sources": [source],
                }
            ],
        }
    )


def prepare_fixture(unit, root):
    from learnloop.evaluation.prepare import author_exams

    freeze(root / "unit.json", unit.model_dump())
    exams = author_exams(unit, FixtureProvider(), root / "exams.json")["payload"]
    validate_exams(unit, exams)
    for variant in EXPERTS:
        build_expert(unit, exams, variant, FixtureProvider(), root / f"expert-{variant}.json")
