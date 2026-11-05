from itertools import product

from learnloop.agents.assessing.prompts import FEEDBACK_PROMPT
from learnloop.agents.expert.prompts import EXPERT_MATERIALS_PROMPT
from learnloop.agents.tutoring.prompts import PLAN_PROMPT
from learnloop.evaluation.schema import ASSESSORS, EXPERTS, TUTORS

EXPERT = {
    "structural": "Organize a clear concept structure and complete all requested resource fields.",
    "grounded": "Prioritize traceable passage support, scope and accurate references in every field.",
    "verified": "Check calculations, misconceptions, level suitability and prerequisite consistency before returning the final artifact.",
}
TUTOR = {
    "state": "Emphasize the estimated current state and recent performance when choosing the next candidate.",
    "graph": "Emphasize graph readiness, prerequisite reinforcement and connected progression when choosing the next candidate.",
    "utility": "Balance candidate need, uncertainty, review urgency, performance and goal relevance using the supplied utilities.",
}
ASSESSOR = {
    "correctness": "Emphasize key correctness and explicit rubric coverage; do not infer unexpressed reasoning.",
    "weighted": "Qualify rubric evidence with hint dependence, prior attempts, timing and contradictions; none can override a wrong key.",
    "conservative": "Flag uncertainty where rubric evidence or reasoning is ambiguous or conflicts with prior evidence; abstain rather than overstate confidence.",
}


def matrix():
    return [
        {"expert": e, "tutor": t, "assessor": a} for e, t, a in product(EXPERTS, TUTORS, ASSESSORS)
    ]


def instruction(role, variant):
    if role == "Expert":
        return EXPERT_MATERIALS_PROMPT + "\nExperimental emphasis: " + EXPERT[variant]
    if role == "Tutoring":
        return PLAN_PROMPT + "\nExperimental emphasis: " + TUTOR[variant]
    return FEEDBACK_PROMPT + "\nExperimental emphasis: " + ASSESSOR[variant]
