from datetime import UTC, datetime, timedelta

from learnloop.evaluation.belief_student import BeliefAnswer, BeliefStudent, BeliefUpdate
from learnloop.evaluation.fixtures import FixtureProvider


def test_only_supported_revision_replaces_the_specific_belief_and_changes_unaided_recall():
    at = datetime(2030, 1, 1, tzinfo=UTC)
    mistake = "Paging explains the entire speedup."
    correction = "Engine changes include both paging and scheduling."
    other = "Caches store keys and values."
    question = {
        "prompt": "What caused the increase?",
        "choices": [{"id": k, "text": k} for k in "abcd"],
        "difficulty": "basic",
        "correctChoiceId": "b",
        "rubric": [],
        "explanation": correction,
    }

    class Recording(FixtureProvider):
        def generate(self, role, instruction, context, output):
            if output is BeliefUpdate:
                return output(
                    revisions=[
                        {"belief": correction, "evidenceQuote": correction, "replaces": mistake}
                    ]
                )
            assert set(context["question"]) == {"prompt", "choices", "difficulty"}
            assert "canAnswerIndependently" not in context
            self.recalled = context["recalledBeliefs"]
            return BeliefAnswer(choiceId="a", reasoning="I am unsure.", uncertain=True)

    provider = Recording()
    recalls = 0
    for seed in range(40):
        for feedback in [other, correction]:
            s = BeliefStudent([{"id": "kv"}], "novice", seed, 0)
            s.spec["hint"] = 1
            s.beliefs = {
                "kv": {
                    mistake: {"source": "prior", "misconception": True},
                    other: {"source": "prior", "misconception": False},
                }
            }
            s.revisions = []
            s.misconceptions.add("kv")
            reply, _ = s.respond(provider, "kv", question, "train", at)
            assert reply.hintRequested
            first = provider.recalled
            aided, _ = s.respond(
                provider, "kv", question, "train", at, hint="Think about scheduling."
            )
            assert not aided.hintRequested and provider.recalled == first
            s.learn(provider, "kv", "basic", reply, None, {"feedback": feedback}, at)
            assert other in s.beliefs["kv"]
            assert (mistake in s.beliefs["kv"]) == (feedback == other)
            assert ("kv" in s.misconceptions) == (feedback == other)
            exam, _ = s.respond(provider, "kv", question, "post", at + timedelta(days=8))
            assert not exam.hintRequested
            recalled = s.policies[-1]["recalledBeliefs"]
            if feedback == correction:
                assert mistake not in recalled
                recalls += correction in recalled
            else:
                assert correction not in recalled
    assert 0 < recalls < 40  # Some students retain the correction over the gap.
