from types import SimpleNamespace

from learnloop.agents.tutoring.agent import select_question_format


def test_basic_starts_simple_then_includes_all_formats():
    expected = ["single_answer", "fill_in", "multiple_answer", "open", "single_answer", "fill_in"]
    previous = [SimpleNamespace(difficulty="intermediate")]
    for question_format in expected:
        assert select_question_format("basic", previous, True) == question_format
        previous.append(SimpleNamespace(difficulty="basic"))
    assert select_question_format("basic", previous, False) == "single_answer"
