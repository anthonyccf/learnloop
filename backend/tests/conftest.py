import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from learnloop.api import create_app
from learnloop.core.config import get_settings
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import (
    AdditionalLessons,
    AdditionalQuestions,
    Assessment,
    ConceptMatches,
    ConceptMaterials,
    CourseRelationships,
    CurriculumPlan,
    DifficultyMaterials,
    ExtendedTopicReview,
    Graph,
    GroundingReview,
    LessonScopeReview,
    PlanChoice,
    PostExample,
    PostLesson,
    PostMaterials,
    PyramidMaterials,
    Question,
    QuestionRubric,
    SectionGraph,
    TopicOrganization,
)
from learnloop.persistence.database import Base, session_factory

COURSE_TEXT = "Gradient descent subtracts the gradient to reduce the loss. A learning rate determines the step size. Small steps help avoid overshooting the minimum."


class FakeServices:
    def __init__(self, settings):
        self.settings, self.chunks, self.questions = settings, {}, 0
        self.fail_next = False
        self.bad_source = False
        self.paraphrase_source = False
        self.grounding_status = "supported"

    def check_collection(self):
        return {"status": "green", "dimensions": 1024}

    def embed(self, text):
        return [0.01] * 1024

    def index(self, chunks, owner_id):
        for c in chunks:
            self.chunks[c["id"]] = {**c, "owner_id": owner_id}

    def search(self, query, owner_id, course_id, document_ids, limit):
        return [
            id
            for id, chunk in self.chunks.items()
            if chunk["owner_id"] == owner_id
            and chunk["course_id"] == course_id
            and chunk["document_id"] in document_ids
        ][:limit]

    def generate(self, role, instruction, context, output):
        if self.fail_next:
            self.fail_next = False
            raise ServiceError("test_timeout", "Temporary test provider failure.")
        if output is GroundingReview:
            return GroundingReview(
                status=self.grounding_status, summary="Controlled source review result."
            )
        if output is ExtendedTopicReview:
            return ExtendedTopicReview(
                approved=False, reason="This test question is not an approved extension."
            )
        if output is Assessment:
            return Assessment(
                feedback="Consider the direction that reduces the loss.",
                uncertain=False,
                coverage=[
                    {
                        "criterionId": c["id"],
                        "score": c["choiceScores"][context["selectedChoiceId"]],
                        "reason": "The selected option expresses this criterion.",
                        "responseQuote": context.get("reasoning") or "",
                    }
                    for c in context.get("rubric", [])
                ],
            )
        if output is PlanChoice:
            return PlanChoice(
                candidateId=context["candidates"][0]["id"],
                rationale="This action addresses the highest-priority eligible learning need.",
            )
        if output is QuestionRubric:
            source = context["passages"][0]
            return QuestionRubric(
                referenceAnswer=context["question"]["explanation"],
                rubric=[
                    {
                        "id": "direction",
                        "description": "Choose the update direction that reduces the loss.",
                        "weight": 1,
                        "choiceScores": {
                            key: float(key == context["question"]["correctChoiceId"])
                            for key in "abcd"
                        },
                        "sources": [{"chunkId": source["chunkId"], "quote": source["text"][:60]}],
                    }
                ],
            )
        if output is ConceptMatches:
            return ConceptMatches(matches=[])
        if output is TopicOrganization:
            return TopicOrganization(
                topics=[
                    {
                        "id": "foundations",
                        "title": "Foundations",
                        "summary": "Course foundations in source order.",
                        "conceptIds": [c["id"] for c in context["concepts"]],
                    }
                ]
            )
        if output is LessonScopeReview:
            return LessonScopeReview(
                accepted=True, feedback="The lesson teaches its assigned exclusive scope."
            )
        if output is CurriculumPlan:
            return CurriculumPlan(
                objectives=[
                    {
                        "conceptId": c["id"],
                        "layer": "basic",
                        "teaches": c["title"] + ": " + c["summary"],
                        "assumes": [],
                        "adds": "Understand this source-supported foundation.",
                    }
                    for c in context["concepts"]
                ]
            )
        if output is CourseRelationships:
            return CourseRelationships(prerequisites=[], related=[])
        passage = context["passages"][0]
        source = {
            "chunkId": "outside-this-document" if self.bad_source else passage["chunkId"],
            "quote": "A paraphrased description of the supplied source."
            if self.paraphrase_source
            else passage["text"][:60],
        }
        if output is PostExample:
            return PostExample(
                title="Hypothetical example",
                steps=[
                    {
                        "title": "Given values",
                        "explanation": "Start with the weight and gradient.",
                        "equations": ["w=4,\\quad g=2,\\quad \\eta=0.1"],
                    },
                    {
                        "title": "Update the weight",
                        "explanation": "Subtract the scaled gradient to reduce the loss.",
                        "equations": ["w_{new}=w-\\eta g", "w_{new}=4-0.1\\times2=3.8"],
                    },
                ],
                explanation="The update moves opposite to the gradient.",
            )
        if output is AdditionalQuestions:
            return AdditionalQuestions(
                tests=[
                    self.generate(role, instruction, {**context, "difficulty": level}, Question)
                    for level in context["requestedDifficulties"]
                ]
            )
        if output is AdditionalLessons:
            return AdditionalLessons(
                basic=self.generate(role, instruction, context, PostLesson),
                advanced=self.generate(role, instruction, context, PostLesson),
            )
        if output in (PostLesson, PostMaterials, DifficultyMaterials, PyramidMaterials):
            post = PostLesson.model_validate(
                {
                    "title": "Gradient descent, one small step",
                    "objective": "Learn how a small update can reduce the loss.",
                    "hook": "A small step can move a weight toward lower loss.",
                    "points": [
                        "**Direction:** The gradient points toward increasing loss.",
                        "**Update:** Subtract a small multiple of the gradient.",
                        "**Step size:** The learning rate controls how far you move.",
                    ],
                    "equations": [],
                    "workedExample": FakeServices.generate(
                        self, role, instruction, context, PostExample
                    ).model_dump(),
                    "takeaway": "Subtract a small multiple of the gradient.",
                    "commonMistake": "Adding the gradient moves toward increasing loss.",
                    "flashcards": [
                        {
                            "front": "What controls the step size?",
                            "back": "The learning rate controls how far each update moves.",
                        }
                    ],
                    "sources": [source],
                }
            )
            if output is PostLesson:
                return post
            variants = (
                {"basicLesson": post, "advancedLesson": post}
                if output is DifficultyMaterials
                else {}
            )
            return output(
                **variants,
                lesson=post,
                tests=[
                    self.generate(role, instruction, {**context, "difficulty": level}, Question)
                    for level in (
                        ["basic", "basic", "intermediate", "intermediate", "advanced", "advanced"]
                        if output in (DifficultyMaterials, PyramidMaterials)
                        else ["intermediate", "intermediate"]
                    )
                ],
            )
        if output in (Graph, SectionGraph):
            return output.model_validate(
                {
                    "concepts": [
                        {
                            "id": "descent",
                            "title": "Gradient descent",
                            "summary": "Subtract the gradient to reduce the loss.",
                            "sources": [source],
                        }
                    ],
                    "prerequisites": [],
                }
            )
        if output is ConceptMaterials:
            return ConceptMaterials.model_validate(
                {
                    "lesson": {
                        "title": "Gradient descent, step by step",
                        "objective": "Explain why a gradient descent update can reduce the loss.",
                        "explanation": "The gradient points toward an increase in loss. To reduce the loss, subtract a small multiple of the gradient. The learning rate controls the size of this step. Small steps help avoid overshooting.",
                        "equations": [
                            {
                                "latex": "w_{new}=w-\\eta g",
                                "explanation": "w is the weight, eta is the positive learning rate, and g is the gradient.",
                            }
                        ],
                        "workedExample": {
                            "title": "Hypothetical example",
                            "steps": [
                                "Start with weight 4, gradient 2, and learning rate 0.1.",
                                "Subtract 0.1 times 2 to get the new weight 3.8.",
                            ],
                            "explanation": "The update moves opposite to the gradient.",
                        },
                        "takeaway": "Subtract a small multiple of the gradient.",
                        "commonMistake": "Adding the gradient moves toward increasing loss.",
                        "flashcards": [
                            {
                                "front": "What controls the step size?",
                                "back": "The learning rate controls the size of each update.",
                            }
                        ],
                        "sources": [source],
                    },
                    "tests": [
                        self.generate(role, instruction, context, Question).model_dump()
                        for _ in range(2)
                    ],
                }
            )
        self.questions += 1
        return Question.model_validate(
            {
                "difficulty": context.get("difficulty", "intermediate"),
                "prompt": f"For example {self.questions}, which update reduces the loss?",
                "choices": [
                    {"id": key, "text": value}
                    for key, value in zip(
                        "abcd",
                        [
                            "Subtract the gradient",
                            "Add the gradient",
                            "Always double weights",
                            "Ignore the gradient",
                        ],
                    )
                ],
                "correctChoiceId": "a",
                "explanation": "Subtract the gradient to move toward lower loss.",
                "hint": "Consider the direction opposite to increase.",
                "sources": [source],
                "referenceAnswer": "Subtract the gradient to move toward lower loss.",
                "rubric": [
                    {
                        "id": "direction",
                        "description": "Choose the update direction that reduces the loss.",
                        "weight": 1,
                        "choiceScores": {"a": 1, "b": 0, "c": 0, "d": 0},
                        "sources": [source],
                    }
                ],
            }
        )


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    # No database server or production records are used by ordinary tests.
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "test.db").as_posix())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stack():
    settings = get_settings().model_copy(
        update={"api_token": SecretStr("test-token"), "local_owner_id": "test-owner"}
    )
    factory = session_factory(settings)
    engine = factory.kw["bind"]
    Base.metadata.create_all(engine)
    services = FakeServices(settings)
    app = create_app(settings, factory, services)
    try:
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer test-token"
            yield client, factory, services, settings
    finally:
        engine.dispose()
