"""Paired paged-KV correction pilot. Run as a module from backend/."""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from learnloop.core.config import get_settings
from learnloop.core.schemas import StrictModel
from learnloop.evaluation.artifacts import write
from learnloop.evaluation.belief_student import BeliefAnswer, BeliefStudent
from learnloop.evaluation.provider import Provider
from learnloop.evaluation.simulator import Student

MISTAKE = "I think paging alone accounts for the entire measured throughput improvement."
FEEDBACK = {
    "targeted": "The two engines differ in scheduling and kernels as well as paging. "
    "Their throughput ratio alone cannot isolate the effect of paging.",
    "control": "A KV cache stores keys and values from earlier tokens during generation. "
    "The engine reuses these entries when processing later tokens.",
}
# Options encode competing explanations. The judge also checks the student's own words.
PROBES = [
    (
        "paged",
        0,
        "Engine A uses paged storage and serves twice as many requests as B. "
        "They also use different schedulers. What can we infer?",
        [
            "Paging explains all of the difference.",
            "Only the combined engine difference was measured.",
            "Both engines have identical throughput.",
            "Paging must reduce throughput.",
        ],
        "b",
    ),
    (
        "paged",
        8,
        "A new server introduces paged caches and new kernels together. "
        "How should we interpret its higher request rate?",
        [
            "Kernel changes explain the entire gain.",
            "Neither change could affect requests.",
            "We need a controlled comparison to attribute a share to paging.",
            "Paging caused all of the gain.",
        ],
        "c",
    ),
    (
        "untaught",
        0,
        "What does a tokenizer produce from text?",
        ["GPU kernels", "Attention weights", "Learning rates", "Token identifiers"],
        "d",
    ),
    (
        "untaught",
        8,
        "Before an embedding lookup, how is a sentence represented?",
        ["Token indices", "Batch throughput", "Learning rates", "Attention scores"],
        "a",
    ),
]


class Recurrence(StrictModel):
    endorsesMisconception: bool


def run_arm(provider, variant, condition, seed):
    concepts = [{"id": "paged"}, {"id": "untaught"}]
    at = datetime(2030, 1, 1, tzinfo=UTC)
    cls = BeliefStudent if variant == "belief" else Student
    student = cls(concepts, "novice", seed, 0)
    student.misconceptions.add("paged")
    if variant == "belief":
        student.beliefs = {
            "paged": {MISTAKE: {"source": "prior", "misconception": True}},
            "untaught": {},
        }
        student.revisions = []
    else:
        student.memory["paged"] = MISTAKE
    prior = BeliefAnswer(choiceId="a", reasoning=MISTAKE, uncertain=False)
    student.learn(provider, "paged", "basic", prior, None, {"feedback": FEEDBACK[condition]}, at)
    rows = []
    for concept, days, prompt, options, key in PROBES:
        question = {
            "prompt": prompt,
            "difficulty": "basic",
            "choices": [{"id": k, "text": v} for k, v in zip("abcd", options)],
        }
        reply, _ = student.respond(provider, concept, question, "post", at + timedelta(days=days))
        recurrence = None
        if concept == "paged":
            judgment = provider.generate(
                "PilotReviewer",
                "Does the student's own explanation endorse the specified "
                "mistaken belief? A quoted or rejected belief is not an endorsement.",
                {"belief": MISTAKE, "explanation": reply.reasoning},
                Recurrence,
            )
            recurrence = judgment.endorsesMisconception
        rows.append(
            {
                "seed": seed,
                "simulator": variant,
                "feedback": condition,
                "concept": concept,
                "days": days,
                "correct": reply.choiceId == key,
                "choice": reply.choiceId,
                "reasoning": reply.reasoning,
                "recalledBeliefs": student.policies[-1].get("recalledBeliefs"),
                "recurrence": recurrence,
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=1)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    rows = []
    for seed in range(72, 72 + args.seeds):
        for variant in ("controlled", "belief"):
            for condition in FEEDBACK:
                path = args.output / f"{seed}-{variant}-{condition}"
                provider = Provider(settings, path / "calls", seed=seed, max_calls=12)
                arm = run_arm(provider, variant, condition, seed)
                write(path / "responses.json", arm)
                rows.extend(arm)
    write(args.output / "responses.json", rows)


if __name__ == "__main__":
    main()
