import pytest

from learnloop.agents.assessing.mixed_answers import assess_mixed
from learnloop.core.errors import ServiceError
from learnloop.core.schemas import Assessment, OpenQuestion


def test_partial_open_response_requires_real_answer_evidence():
    source = {"chunkId": "chunk-1", "quote": "A passage about the block table and physical blocks."}
    question = OpenQuestion(
        difficulty="basic", prompt="What does the block table track?",
        explanation="It maps the sequence to physical blocks.", hint="Think about the mapping.",
        sources=[source], referenceAnswer="It maps the sequence to physical blocks.",
        rubric=[{"id": "mapping", "description": "Relates the sequence to physical blocks.",
                 "weight": 1, "sources": [source]}],
    )

    class Assessor:
        quote = "physical blocks"

        def generate(self, role, instruction, context, output):
            assert output is Assessment
            assert "a value strictly between 0 and 1" in instruction
            return Assessment(feedback="You identified the blocks; explain their mapping.", uncertain=False,
                              coverage=[{"criterionId": "mapping", "score": 0.5,
                                         "reason": "Identifies blocks but not the mapping.",
                                         "responseQuote": self.quote}])

    assessor = Assessor()
    answer = {"answerText": "physical blocks store tokens"}
    _, coverage, score = assess_mixed(assessor, question, {}, answer)
    assert score == 0.5 and coverage[0]["responseQuote"] == "physical blocks"
    assessor.quote = "a mapping not in the answer"
    with pytest.raises(ServiceError, match="Rubric credit must cite"):
        assess_mixed(assessor, question, {}, answer)
