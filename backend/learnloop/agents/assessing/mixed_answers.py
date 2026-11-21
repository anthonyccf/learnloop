"""Grade typed responses while leaving mastery decisions to the evidence rules."""

from learnloop.agents.assessing.prompts import BLANK_EQUIVALENCE_PROMPT, OPEN_FEEDBACK_PROMPT
from learnloop.core.errors import ServiceError
from learnloop.core.question_formats import blank_matches
from learnloop.core.schemas import Assessment, FillInQuestion, MultipleAnswerQuestion, StrictModel


class BlankEquivalence(StrictModel):
    possibleEquivalence: bool


def assess_mixed(services, question, context, answer):
    scores, by_id = {}, {}
    if isinstance(question, MultipleAnswerQuestion):
        selected = set(answer["choiceIds"])
        correct = set(question.correctChoiceIds)
        exact = selected == correct
        mapped = all(c.choiceIds for c in question.rubric)
        scores = {c.id: (len(selected.intersection(c.choiceIds)) / len(c.choiceIds)
                         if mapped else float(exact)) for c in question.rubric}
        missed = ", ".join(choice.text for choice in question.choices if choice.id in correct - selected)
        incorrect = ", ".join(choice.text for choice in question.choices if choice.id in selected - correct)
        details = " ".join(filter(None, [f"Missed: {missed}." if missed else "",
                                          f"Incorrectly selected: {incorrect}." if incorrect else ""]))
        output = Assessment(
            feedback="You identified the complete set."
            if exact
            else f"You selected {len(selected & correct)} of {len(correct)} correct options. {details}"[:1500],
            uncertain=False,
        )
    elif isinstance(question, FillInQuestion):
        values = answer["blanks"]
        scores = {
            blank.id: float(blank_matches(blank, values[blank.id])) for blank in question.blanks
        }
        rejected = [blank for blank in question.blanks if not scores[blank.id]]
        uncertain = (
            bool(rejected)
            and services.generate(
                "Assessing",
                BLANK_EQUIVALENCE_PROMPT,
                {
                    "question": question.prompt,
                    "passages": context["passages"],
                    "unmatched": [
                        {**blank.model_dump(), "submitted": values[blank.id]} for blank in rejected
                    ],
                },
                BlankEquivalence,
            ).possibleEquivalence
        )
        output = Assessment(
            feedback="All blanks match the answer key."
            if not rejected
            else "This answer may need another check."
            if uncertain
            else "Review the unmatched blanks and their required terms or units.",
            uncertain=uncertain,
        )
    else:
        response = answer["answerText"]
        output = services.generate(
            "Assessing",
            OPEN_FEEDBACK_PROMPT,
            {**context, "answerText": response},
            Assessment,
        )
        by_id = {c.criterionId: c for c in output.coverage}
        if len(by_id) != len(output.coverage) or set(by_id) != {c.id for c in question.rubric}:
            raise ServiceError(
                "invalid_rubric_assessment", "Assessment must cover each criterion once.", False
            )
        for item in output.coverage:
            if (item.score > 0 or item.responseQuote) and (
                not item.responseQuote or item.responseQuote not in response
            ):
                raise ServiceError(
                    "invalid_response_evidence",
                    "Rubric credit must cite the learner's answer.",
                    False,
                )
        for item in output.misconceptions:
            if (
                item.criterionId not in by_id
                or item.responseQuote not in response
                or by_id[item.criterionId].score == 1
            ):
                raise ServiceError(
                    "invalid_response_evidence",
                    "The misconception conflicts with the response or rubric.",
                    False,
                )

    coverage = []
    for criterion in question.rubric:
        item = by_id[criterion.id] if not scores else None
        score = item.score if item else scores[criterion.id]
        coverage.append(
            {
                "criterionId": criterion.id,
                "description": criterion.description,
                "weight": criterion.weight,
                "score": score,
                "reason": item.reason
                if item
                else ("Credit reflects the correct choices identified for this criterion."
                      if isinstance(question, MultipleAnswerQuestion) and mapped
                      else "Matched the private key." if score else "Did not match the private key."),
                "responseQuote": item.responseQuote if item else "",
            }
        )
    score = sum(c["weight"] * c["score"] for c in coverage) / sum(c["weight"] for c in coverage)
    return output, coverage, score
