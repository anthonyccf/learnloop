"""Deliberately simple workflow fixtures. Not a research simulator or question bank."""

from learnloop.core.schemas import (
    Assessment,
    DifficultyMaterials,
    Graph,
    GroundingReview,
    PlanChoice,
)
from learnloop.evaluation.artifacts import freeze
from learnloop.evaluation.prepare import build_expert, validate_exams
from learnloop.evaluation.provider import BudgetExhausted
from learnloop.evaluation.schema import EXPERTS, ExamDraft, LearningUpdate, StudentReply


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
        if output is LearningUpdate:
            return LearningUpdate(
                memoryUpdate="Remember the claim explained in the delivered feedback.",
                learningGain=0.08,
                misconceptionResolved=True,
            )
        if output is Assessment:
            return Assessment(
                feedback="Controlled workflow feedback only.",
                uncertain=False,
                coverage=[
                    {
                        "criterionId": c["id"],
                        "score": c["choiceScores"][context["selectedChoiceId"]],
                        "reason": "Controlled criterion coverage.",
                        "responseQuote": context["reasoning"],
                    }
                    for c in context["rubric"]
                ],
                misconceptions=[],
                contradiction=False,
            )
        raise ValueError(f"Unsupported fixture output: {output.__name__}")


def prepare_fixture(unit, root):
    from learnloop.evaluation.prepare import author_exams

    freeze(root / "unit.json", unit.model_dump())
    exams = author_exams(unit, FixtureProvider(), root / "exams.json")["payload"]
    validate_exams(unit, exams)
    for variant in EXPERTS:
        build_expert(unit, exams, variant, FixtureProvider(), root / f"expert-{variant}.json")
