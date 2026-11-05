from typing import Literal

from pydantic import Field, model_validator

from learnloop.core.domain import validate_graph
from learnloop.core.grounding import validate_sources
from learnloop.core.schemas import Graph, Question, StrictModel

EXPERTS = ("structural", "grounded", "verified")
TUTORS = ("state", "graph", "utility")
ASSESSORS = ("correctness", "weighted", "conservative")
PROFILES = ("novice", "intermediate", "misconception_prone", "hint_dependent")


class Passage(StrictModel):
    id: str
    text: str = Field(min_length=40)
    document: str
    page: int = Field(ge=1)


class Unit(StrictModel):
    id: str
    title: str
    sourceSha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    passages: list[Passage] = Field(min_length=1)
    graph: Graph
    scopeWarnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_unit(self):
        if not 10 <= len(self.graph.concepts) <= 20:
            raise ValueError("Research units require 10–20 concepts")
        if len({p.id for p in self.passages}) != len(self.passages):
            raise ValueError("Passage IDs must be unique")
        validate_graph(self.graph)
        validate_sources(self.graph, self.chunks())
        return self

    def chunks(self):
        return {p.id: {"id": p.id, "text": p.text} for p in self.passages}


class ExamItem(StrictModel):
    id: str
    conceptId: str
    question: Question


class ExamDraft(StrictModel):
    pre: list[Question] = Field(min_length=3, max_length=3)
    post: list[Question] = Field(min_length=3, max_length=3)


class StudentReply(StrictModel):
    choiceId: Literal["a", "b", "c", "d"]
    reasoning: str = Field(min_length=1, max_length=600)
    hintRequested: bool
    memoryUpdate: str = Field(max_length=400)
    learningGain: float = Field(ge=0, le=0.15)


class LearningUpdate(StrictModel):
    memoryUpdate: str = Field(max_length=600)
    learningGain: float = Field(ge=0, le=0.15)
    misconceptionResolved: bool


class Screening(StrictModel):
    supported: bool
    appropriateDifficulty: bool
    prerequisiteAccuracy: bool
    notes: str = Field(min_length=5, max_length=1000)


class ExperimentConfig(StrictModel):
    seed: int = 72
    repeats: int = Field(default=3, ge=1, le=100)
    activities: int = Field(default=24, ge=2, le=500)
    sessions: int = Field(default=2, ge=2, le=10)
    sessionGapDays: int = Field(default=8, ge=0, le=365)
    maxCalls: int = Field(default=256, ge=1)
    maxTokens: int = Field(default=150000, ge=1000)
    model: str = "configured"
    temperature: float = Field(default=0.2, ge=0, le=2)
    postTarget: float = Field(default=0.8, gt=0, le=1)
    minPolicyAgreement: float = Field(default=0.75, ge=0.5, le=1)

    @model_validator(mode="after")
    def feasible_sessions(self):
        if self.sessions > self.activities:
            raise ValueError("Each simulated session requires at least one activity")
        return self
