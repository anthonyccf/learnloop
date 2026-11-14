"""Shared question formats and the public prompt projection."""

import unicodedata

from learnloop.core.schemas import FillInQuestion, MultipleAnswerQuestion, OpenQuestion, Question

QUESTION_MODELS = {
    "single_answer": Question,
    "multiple_answer": MultipleAnswerQuestion,
    "fill_in": FillInQuestion,
    "open": OpenQuestion,
}


def parse_question(item):
    return QUESTION_MODELS[item.get("format", "single_answer")].model_validate(item)


def blank_matches(blank, value):
    def normalize(text):
        text = " ".join(unicodedata.normalize("NFKC", text).split())
        return text if blank.caseSensitive else text.casefold()

    return normalize(value) in {normalize(answer) for answer in blank.acceptedAnswers}


def public_prompt(question):
    result = {"prompt": question.prompt, "choices": []}
    if isinstance(question, (Question, MultipleAnswerQuestion)):
        result["choices"] = [choice.model_dump() for choice in question.choices]
    if not isinstance(question, Question):
        result["format"] = question.format
    if isinstance(question, FillInQuestion):
        result["blankIds"] = [blank.id for blank in question.blanks]
    return result
