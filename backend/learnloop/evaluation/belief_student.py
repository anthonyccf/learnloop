"""Exploratory learner whose answers depend on recalled concept beliefs."""

import copy
import random
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from learnloop.core.schemas import StrictModel
from learnloop.evaluation.artifacts import digest, public_question
from learnloop.evaluation.schema import StudentBlankAnswer
from learnloop.evaluation.simulator import LEVELS, Student


class BeliefAnswer(StrictModel):
    choiceId: Literal["a", "b", "c", "d"]
    reasoning: str = Field(min_length=1, max_length=600)
    uncertain: bool
    hintRequested: bool = False


class MixedBeliefAnswer(StrictModel):
    choiceIds: list[Literal["a", "b", "c", "d"]] = Field(default_factory=list, max_length=4)
    blanks: list[StudentBlankAnswer] = Field(default_factory=list, max_length=6)
    answerText: str = Field(default="", max_length=4000)
    reasoning: str = Field(min_length=1, max_length=600)
    uncertain: bool
    hintRequested: bool = False


class InitialMisconception(StrictModel):
    belief: str = Field(min_length=1, max_length=400)


class Revision(StrictModel):
    belief: str = Field(min_length=1, max_length=400)
    evidenceQuote: str = Field(min_length=1, max_length=400)
    replaces: str | None


class BeliefUpdate(StrictModel):
    revisions: list[Revision] = Field(max_length=3)


class BeliefStudent(Student):
    def initialize_beliefs(self, materials, provider):
        self.beliefs = {}
        self.revisions = []
        for concept_id in self.knowledge:
            lesson = materials[concept_id]["content"]["basicLesson"]
            records = self.beliefs[concept_id] = {}
            for card in lesson["flashcards"]:
                records[card["back"]] = {"source": "prior", "misconception": False}
            if concept_id in self.misconceptions:
                mistake = provider.generate(
                    "Simulator",
                    "State only the mistaken belief a learner would hold, in the first person. "
                    "Extract it from this common mistake description. Omit the correction.",
                    {"commonMistake": lesson["commonMistake"]},
                    InitialMisconception,
                )
                records[mistake.belief] = {"source": "prior", "misconception": True}

    def snapshot(self):
        return {
            **super().snapshot(),
            "beliefs": copy.deepcopy(getattr(self, "beliefs", {})),
            "revisions": copy.deepcopy(getattr(self, "revisions", [])),
        }

    def respond(self, provider, concept_id, question, phase, at, lesson=None, hint=None):
        level = question["difficulty"]
        key = (phase, concept_id, level)
        ordinal = self.counts.get(key, 0)
        if hint is None:
            self.counts[key] = ordinal + 1
        else:
            ordinal -= 1  # A hint belongs to the same attempt and recalled beliefs.
        attempt = [self.seed, self.profile, self.repeat, *key, ordinal]
        recalled = []
        for belief, record in self.beliefs[concept_id].items():
            strength = self.spec["ability"][LEVELS.index(level)]
            if record["misconception"]:
                strength = 1.0
            since = datetime(2030, 1, 1, tzinfo=UTC)
            if record["source"] == "feedback":
                since = datetime.fromisoformat(record["at"])
                # Recent explicit feedback gives an additional route to recall.
                strength += (1 - strength) * record["retention"]
            elapsed = max(0, (at - since).total_seconds() / 86400)
            draw = random.Random(digest([*attempt, belief])).random()
            if draw < strength * 0.98**elapsed:
                recalled.append(belief)
        train = phase == "train"
        kind = question.get("format", "single_answer")
        if not recalled and not (train and (hint or lesson)):
            guess_rng = random.Random(digest([*attempt, "guess"]))
            if kind == "single_answer":
                option = guess_rng.choice(question["choices"])
                reply = BeliefAnswer(
                    choiceId=option["id"],
                    uncertain=True,
                    reasoning="I cannot recall a reason to favor one choice, so I am guessing.",
                )
            elif kind == "multiple_answer":
                option = guess_rng.choice(question["choices"])
                reply = MixedBeliefAnswer(
                    choiceIds=[option["id"]],
                    uncertain=True,
                    reasoning="I cannot recall a reason to favor specific choices, so I am guessing.",
                )
            elif kind == "fill_in":
                reply = MixedBeliefAnswer(
                    blanks=[
                        StudentBlankAnswer(id=blank_id, text="unsure")
                        for blank_id in question.get("blankIds", [])
                    ],
                    uncertain=True,
                    reasoning="I cannot recall the terms for these blanks, so I am guessing.",
                )
            else:
                reply = MixedBeliefAnswer(
                    answerText="I am not sure.",
                    uncertain=True,
                    reasoning="I cannot recall enough to answer this question.",
                )
        elif kind == "single_answer":
            reply = provider.generate(
                "Simulator",
                "Answer as a student using your recalled beliefs, the public question and any "
                "delivered teaching or hint. Treat the beliefs as your own, even when incomplete. "
                "Apply relevant beliefs to this situation. If evidence is missing, make a tentative "
                "choice and mark uncertain. Explain your choice briefly. Avoid supplying expert "
                "facts from outside this context. Never mention simulator controls.",
                {
                    "question": public_question(question),
                    "recalledBeliefs": recalled,
                    "teaching": lesson if train else None,
                    "hint": hint if train else None,
                },
                BeliefAnswer,
            )
        else:
            format_guidance = {
                "multiple_answer": "Put every option ID you select into choiceIds, and leave blanks and answerText empty.",
                "fill_in": "Put one concise term or phrase per ID in question.blankIds into blanks (matching each id exactly), and leave choiceIds and answerText empty.",
                "open": "Put your concise written answer into answerText, and leave choiceIds and blanks empty.",
            }.get(kind, "")
            reply = provider.generate(
                "Simulator",
                "Answer as a student using your recalled beliefs, the public question and any "
                "delivered teaching or hint. Treat the beliefs as your own, even when incomplete. "
                "Apply relevant beliefs to this situation. "
                + format_guidance
                + " If evidence is missing, make a tentative answer and mark uncertain. Explain "
                "your reasoning briefly. Avoid supplying expert facts from outside this context. "
                "Never mention simulator controls.",
                {
                    "question": public_question(question),
                    "recalledBeliefs": recalled,
                    "teaching": lesson if train else None,
                    "hint": hint if train else None,
                },
                MixedBeliefAnswer,
            )
        rng = random.Random(digest([*attempt, "assistance", hint is not None]))
        reply.hintRequested = (
            train and hint is None and reply.uncertain and rng.random() < self.spec["hint"]
        )
        self.policies.append(
            {
                "phase": phase,
                "conceptId": concept_id,
                "difficulty": level,
                "recalledBeliefs": recalled,
                "uncertain": reply.uncertain,
                "reasoning": reply.reasoning,
                "hintAvailable": hint is not None,
                "correct": None,
            }
        )
        return reply, int(self.spec["delay"] * rng.uniform(0.8, 1.2))

    def adherence(self):
        return None  # This simulator does not prescribe answer correctness.

    def learn(self, provider, id, level, reply, lesson, feedback, at):
        records = self.beliefs[id]
        delivered = list(feedback.values())
        if lesson:
            delivered.extend(
                [
                    lesson.get("explanation", ""),
                    lesson.get("takeaway", ""),
                    *lesson.get("points", []),
                ]
            )
        update = provider.generate(
            "Simulator",
            "Record distinct rules learned from the supplied teaching, hint and answer feedback. "
            "Each revision must cite an exact supporting substring from deliveredText. If it specifically "
            "corrects an existing belief, copy that entire old belief into replaces. Otherwise "
            "use null. Preserve unrelated beliefs. Return no revisions for uninformative feedback.",
            {
                "existingBeliefs": list(records),
                "priorResponse": reply.reasoning,
                "deliveredText": delivered,
            },
            BeliefUpdate,
        )
        for revision in update.revisions:
            quote = revision.evidenceQuote.strip()
            if not quote or not any(quote in value for value in delivered):
                continue
            if revision.replaces is not None and revision.replaces not in records:
                continue
            if self.spec["gain"] <= 0:
                continue
            previous = records.get(revision.belief, {})
            records.pop(revision.replaces, None)
            # Initial encoding and later reinforcement are pilot assumptions.
            retention = min(1.0, previous.get("retention", 0.5) + self.spec["gain"])
            records[revision.belief] = {
                "source": "feedback",
                "misconception": False,
                "at": at.isoformat(),
                "retention": retention,
            }
            self.revisions.append({"conceptId": id, "at": at.isoformat(), **revision.model_dump()})
        if not any(record["misconception"] for record in records.values()):
            self.misconceptions.discard(id)
