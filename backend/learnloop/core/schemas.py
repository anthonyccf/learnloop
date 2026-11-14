import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Difficulty = Literal["basic", "intermediate", "advanced"]
ChoiceId = Literal["a", "b", "c", "d"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CourseCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)


class CourseRename(StrictModel):
    title: str = Field(min_length=1, max_length=200)


class DocumentRename(StrictModel):
    title: str = Field(min_length=1, max_length=235, pattern=r"^[^/\\]+$")


class ExpertPromptStages(StrictModel):
    analysis: str = Field(min_length=1, max_length=20000)
    lesson: str = Field(min_length=1, max_length=20000)
    questions: str = Field(min_length=1, max_length=20000)


class ExpertPromptTemplate(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    agent: Literal["expert"]
    name: str = Field(min_length=1, max_length=200)
    prompts: ExpertPromptStages
    enabledTools: list[str] = Field(default_factory=list, max_length=16)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(ge=0, le=2)


class DocumentAnalyzeRequest(StrictModel):
    promptTemplate: ExpertPromptTemplate | None = None
    force: bool = False


class Source(StrictModel):
    chunkId: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=10, max_length=600)


class Concept(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    title: str = Field(min_length=1, max_length=150)
    summary: str = Field(min_length=10, max_length=1000)
    sources: list[Source] = Field(min_length=1, max_length=4)
    targetDifficulty: Difficulty = "intermediate"


class Edge(StrictModel):
    prerequisite: str
    dependent: str
    source: Source


class Graph(StrictModel):
    concepts: list[Concept] = Field(min_length=1)
    prerequisites: list[Edge] = Field(default_factory=list)


class SectionGraph(Graph):
    # Title/agenda/reference sections may contain no new learning goals.
    concepts: list[Concept] = Field(default_factory=list)


class ConceptMatch(StrictModel):
    candidateId: str
    existingId: str


class ConceptMatches(StrictModel):
    matches: list[ConceptMatch] = Field(default_factory=list)


class TopicGroup(StrictModel):
    id: str
    title: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=10, max_length=500)
    conceptIds: list[str] = Field(min_length=1)


class TopicOrganization(StrictModel):
    topics: list[TopicGroup] = Field(min_length=1)


class PrerequisiteLink(StrictModel):
    prerequisite: str
    dependent: str
    rationale: str = Field(min_length=10, max_length=400)
    sourceChunkIds: list[str] = Field(min_length=1, max_length=4)


class RelatedLink(StrictModel):
    first: str
    second: str
    rationale: str = Field(min_length=10, max_length=400)


class CourseRelationships(StrictModel):
    prerequisites: list[PrerequisiteLink] = Field(default_factory=list)
    related: list[RelatedLink] = Field(default_factory=list)


class Choice(StrictModel):
    id: Literal["a", "b", "c", "d"]
    text: str = Field(min_length=1, max_length=600)


class ChoiceScores(StrictModel):
    a: float = Field(ge=0, le=1)
    b: float = Field(ge=0, le=1)
    c: float = Field(ge=0, le=1)
    d: float = Field(ge=0, le=1)


class WrittenCriterion(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")
    description: str = Field(min_length=10, max_length=500)
    weight: int = Field(ge=1, le=5)
    sources: list[Source] = Field(min_length=1, max_length=4)


class RubricCriterion(WrittenCriterion):
    choiceScores: ChoiceScores


class QuestionRubric(StrictModel):
    referenceAnswer: str = Field(min_length=10, max_length=1500)
    rubric: list[RubricCriterion] = Field(min_length=1, max_length=5)


class Question(StrictModel):
    difficulty: Difficulty = "intermediate"
    prompt: str = Field(min_length=10, max_length=1500)
    explanation: str = Field(min_length=10, max_length=1500)
    hint: str = Field(min_length=5, max_length=600)
    choices: list[Choice] = Field(min_length=4, max_length=4)
    correctChoiceId: Literal["a", "b", "c", "d"]
    sources: list[Source] = Field(min_length=1, max_length=4)
    referenceAnswer: str | None = Field(default=None, min_length=10, max_length=1500)
    rubric: list[RubricCriterion] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def distinct_choices(self):
        if {c.id for c in self.choices} != {"a", "b", "c", "d"} or len(
            {c.text.casefold() for c in self.choices}
        ) != 4:
            raise ValueError("Four distinct options are required")
        if self.rubric:
            if not self.referenceAnswer or len({c.id for c in self.rubric}) != len(self.rubric):
                raise ValueError("A rubric needs a reference answer and distinct criterion IDs")
            totals = {
                key: sum(c.weight * getattr(c.choiceScores, key) for c in self.rubric)
                for key in "abcd"
            }
            maximum = sum(c.weight for c in self.rubric)
            if totals[self.correctChoiceId] != maximum or any(
                totals[key] >= maximum for key in "abcd" if key != self.correctChoiceId
            ):
                raise ValueError("Only the correct option may meet the full rubric")
        return self


class OpenQuestion(StrictModel):
    format: Literal["open"] = "open"
    difficulty: Difficulty
    prompt: str = Field(min_length=10, max_length=1500)
    explanation: str = Field(min_length=10, max_length=1500)
    hint: str = Field(min_length=5, max_length=600)
    sources: list[Source] = Field(min_length=1, max_length=4)
    referenceAnswer: str = Field(min_length=10, max_length=1500)
    rubric: list[WrittenCriterion] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_criteria(self):
        if len({criterion.id for criterion in self.rubric}) != len(self.rubric):
            raise ValueError("Use distinct rubric criterion IDs")
        return self


class MultipleAnswerQuestion(OpenQuestion):
    format: Literal["multiple_answer"] = "multiple_answer"
    choices: list[Choice] = Field(min_length=4, max_length=4)
    correctChoiceIds: list[ChoiceId] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_options(self):
        if {c.id for c in self.choices} != set("abcd") or len({c.text.casefold() for c in self.choices}) != 4:
            raise ValueError("Provide four distinct choices")
        if len(set(self.correctChoiceIds)) != len(self.correctChoiceIds):
            raise ValueError("Provide distinct correct choices and at least one distractor")
        return self


class BlankAnswer(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")
    text: str = Field(min_length=1, max_length=400)


class BlankKey(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")
    acceptedAnswers: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(min_length=1, max_length=6)
    caseSensitive: bool = False


class FillInQuestion(OpenQuestion):
    format: Literal["fill_in"] = "fill_in"
    blanks: list[BlankKey] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_blanks(self):
        ids = {blank.id for blank in self.blanks}
        if len(ids) != len(self.blanks) or ids != {criterion.id for criterion in self.rubric}:
            raise ValueError("Use one rubric criterion for each distinct blank ID")
        markers = re.findall(r"\[\[([^\[\]]+)\]\]", self.prompt)
        if len(markers) != len(ids) or set(markers) != ids:
            raise ValueError("Mark every blank exactly once in the prompt using [[id]]")
        return self


class ExpertSolution(StrictModel):
    uncertain: bool
    choiceIds: list[ChoiceId] = Field(default_factory=list, max_length=4)
    blanks: list[BlankAnswer] = Field(default_factory=list, max_length=4)
    answerText: str = Field(default="", max_length=1500)


class CriterionCoverage(StrictModel):
    criterionId: str = Field(min_length=1, max_length=41)
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=5, max_length=500)
    responseQuote: str = Field(default="", max_length=600)


class Misconception(StrictModel):
    criterionId: str = Field(min_length=1, max_length=41)
    description: str = Field(min_length=10, max_length=500)
    responseQuote: str = Field(min_length=1, max_length=600)


class Assessment(StrictModel):
    feedback: str = Field(min_length=5, max_length=1500)
    uncertain: bool
    coverage: list[CriterionCoverage] = Field(default_factory=list, max_length=5)
    misconceptions: list[Misconception] = Field(default_factory=list, max_length=5)
    contradiction: bool = False


class GroundingReview(StrictModel):
    status: Literal["supported", "unsupported", "uncertain"]
    summary: str = Field(min_length=5, max_length=600)


class ExtendedTopicReview(StrictModel):
    approved: bool
    reason: str = Field(min_length=10, max_length=600)


class ExampleStep(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    explanation: str = Field(min_length=5, max_length=260)
    equations: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(
        default_factory=list, max_length=3
    )


class WorkedExample(StrictModel):
    title: str = Field(min_length=1, max_length=150)
    steps: list[str | ExampleStep] = Field(min_length=2, max_length=8)
    explanation: str = Field(min_length=10, max_length=1200)


class Flashcard(StrictModel):
    front: str = Field(min_length=5, max_length=400)
    back: str = Field(min_length=10, max_length=1000)


class Equation(StrictModel):
    latex: str = Field(min_length=1, max_length=400)
    explanation: str = Field(min_length=10, max_length=1200)


class Lesson(StrictModel):
    title: str = Field(min_length=1, max_length=150)
    objective: str = Field(min_length=10, max_length=500)
    explanation: str = Field(min_length=80, max_length=5000)
    equations: list[Equation] = Field(default_factory=list, max_length=3)
    workedExample: WorkedExample
    takeaway: str = Field(min_length=10, max_length=600)
    commonMistake: str = Field(min_length=10, max_length=1000)
    flashcards: list[Flashcard] = Field(min_length=1, max_length=3)
    sources: list[Source] = Field(min_length=1, max_length=4)


class ConceptMaterials(StrictModel):
    lesson: Lesson
    tests: list[Question] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def distinct_tests(self):
        if self.tests[0].prompt.casefold().strip() == self.tests[1].prompt.casefold().strip():
            raise ValueError("Prepare two distinct test questions")
        return self


class PostExample(WorkedExample):
    title: str = Field(min_length=1, max_length=100)
    steps: list[ExampleStep] = Field(min_length=2, max_length=8)
    explanation: str = Field(min_length=10, max_length=320)


class PostLesson(StrictModel):
    """Short teaching blocks, converted to safe Markdown for existing lesson readers."""

    title: str = Field(min_length=1, max_length=110)
    objective: str = Field(min_length=10, max_length=180)
    hook: str = Field(min_length=10, max_length=180)
    points: list[Annotated[str, Field(min_length=10, max_length=220)]] = Field(
        min_length=3, max_length=6
    )
    equations: list[Equation] = Field(default_factory=list, max_length=2)
    workedExample: PostExample
    takeaway: str = Field(min_length=10, max_length=220)
    commonMistake: str = Field(min_length=10, max_length=280)
    flashcards: list[Flashcard] = Field(min_length=1, max_length=2)
    sources: list[Source] = Field(min_length=1, max_length=4)

    def as_lesson(self):
        data = self.model_dump(exclude={"hook", "points"})
        data["explanation"] = (
            self.hook + "\n\n" + "\n".join("- " + point.replace("\n", " ") for point in self.points)
        )
        return Lesson.model_validate(data).model_dump()


class PostMaterials(ConceptMaterials):
    lesson: PostLesson


class AdditionalQuestions(StrictModel):
    tests: list[Question] = Field(min_length=1, max_length=6)


class AdditionalLessons(StrictModel):
    basic: PostLesson
    advanced: PostLesson


class DifficultyMaterials(PostMaterials):
    tests: list[Question] = Field(min_length=6, max_length=6)
    basicLesson: PostLesson
    advancedLesson: PostLesson

    @model_validator(mode="after")
    def complete_difficulties(self):
        if any(
            sum(q.difficulty == level for q in self.tests) != 2
            for level in ("basic", "intermediate", "advanced")
        ):
            raise ValueError("Prepare two questions at each difficulty")
        if len({q.prompt.casefold().strip() for q in self.tests}) != 6:
            raise ValueError("All six question prompts must be distinct")
        if any(not q.rubric or not q.referenceAnswer for q in self.tests):
            raise ValueError(
                "Every new question requires a source-backed rubric and reference answer"
            )
        return self


class ConceptTargetUpdate(StrictModel):
    targetDifficulty: Difficulty
    expectedLearnerVersion: int = Field(ge=0)


class ContinueSession(StrictModel):
    expectedLearnerVersion: int = Field(ge=0)
    mixedQuestionFormats: bool = False


class StartSession(ContinueSession):
    conceptId: str | None = Field(default=None, min_length=1, max_length=100)


class SubmitAnswer(StrictModel):
    operationId: str = Field(min_length=1, max_length=100)
    expectedLearnerVersion: int = Field(ge=0)
    choiceId: ChoiceId | None = None
    choiceIds: list[ChoiceId] | None = Field(default=None, min_length=1, max_length=4)
    blanks: list[BlankAnswer] | None = Field(default=None, min_length=1, max_length=4)
    answerText: str | None = Field(default=None, min_length=1, max_length=4000)
    reasoning: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def one_answer(self):
        if sum(value is not None for value in (self.choiceId, self.choiceIds, self.blanks, self.answerText)) != 1:
            raise ValueError("Submit one answer in the activity's question format")
        if self.reasoning and self.choiceId is None:
            raise ValueError("Optional reasoning is available for single-answer questions")
        if self.choiceIds is not None and len(set(self.choiceIds)) != len(self.choiceIds):
            raise ValueError("Select distinct options")
        if self.blanks is not None and len({blank.id for blank in self.blanks}) != len(self.blanks):
            raise ValueError("Fill each blank once")
        return self

    def typed_answer(self):
        if self.choiceIds is not None:
            return {"choiceIds": sorted(self.choiceIds)}
        if self.blanks is not None:
            return {"blanks": {blank.id: blank.text for blank in self.blanks}}
        return {"answerText": self.answerText} if self.answerText is not None else None


class LearningGoal(StrictModel):
    description: str = Field(
        default="Build independent understanding of this course.", min_length=5, max_length=600
    )
    conceptIds: list[str] = Field(default_factory=list, max_length=100)


class ReviewDate(StrictModel):
    conceptId: str = Field(min_length=1, max_length=100)
    reviewAt: str = Field(min_length=1, max_length=50)


class RevisePlan(StrictModel):
    operationId: str = Field(min_length=1, max_length=100)
    expectedPlanVersion: int = Field(ge=0)
    expectedLearnerVersion: int = Field(ge=0)
    goal: LearningGoal
    activityIds: list[str] = Field(default_factory=list, max_length=100)
    reviewDates: list[ReviewDate] = Field(default_factory=list, max_length=100)


class PlanChoice(StrictModel):
    candidateId: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=10, max_length=600)


class TutorChatTurn(StrictModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=6000)


class TutorChatRequest(StrictModel):
    activityId: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    history: list[TutorChatTurn] = Field(default_factory=list, max_length=12)


class TutorObservation(StrictModel):
    kind: Literal["strength", "gap"]
    summary: str = Field(min_length=10, max_length=240)
    quote: str = Field(min_length=5, max_length=240)


class TutorChatReply(StrictModel):
    text: str = Field(min_length=1, max_length=6000)
    observation: TutorObservation | None = None


class RunCommand(StrictModel):
    kind: Literal["retry", "resume"]
    operationId: str = Field(min_length=1, max_length=100)
    expectedVersion: int = Field(ge=0)


class Search(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=10)


class CurriculumObjective(StrictModel):
    conceptId: str
    layer: Difficulty
    teaches: str = Field(min_length=10, max_length=700)
    assumes: list[str] = Field(default_factory=list)
    adds: str = Field(min_length=10, max_length=500)


class CurriculumPlan(StrictModel):
    objectives: list[CurriculumObjective] = Field(min_length=1)


class PyramidMaterials(PostMaterials):
    @model_validator(mode="after")
    def starter_bank(self):
        if any(q.difficulty != "basic" for q in self.tests):
            raise ValueError("Prepare two Basic starter questions")
        if any(not q.rubric or not q.referenceAnswer for q in self.tests):
            raise ValueError("Every question requires a rubric and reference answer")
        return self


class QuestionKeyCheck(StrictModel):
    answers: list[Literal["a", "b", "c", "d", "uncertain"]] = Field(min_length=1, max_length=2)


class LessonScopeReview(StrictModel):
    accepted: bool
    feedback: str = Field(min_length=10, max_length=1200)
