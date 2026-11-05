"""Small live workflow test, explicitly ineligible for research analysis."""

from learnloop.agents.grounding import generate_grounded
from learnloop.core.schemas import DifficultyMaterials
from learnloop.evaluation.artifacts import digest, freeze, prompt_key
from learnloop.evaluation.provider import usage
from learnloop.evaluation.runner import run_episode
from learnloop.evaluation.schema import ExamDraft, ExperimentConfig
from learnloop.evaluation.variants import instruction


def canary(unit, preparation, episode_provider, destination):
    concept = unit.graph.concepts[0]
    context = {
        "concept": concept.model_dump(),
        "passages": [
            {"chunkId": p.id, "text": p.text}
            for p in unit.passages
            if p.id in {s.chunkId for s in concept.sources}
        ],
    }
    draft, _ = generate_grounded(
        preparation,
        "TestAuthor",
        "Author independent pre and post tests, each with one Basic, Intermediate and Advanced MCQ for this source concept. Include complete private reference answers and source-cited weighted rubrics/choiceScores. Use distinct prompts, numbers or cases for each exam.",
        context,
        ExamDraft,
        unit.chunks(),
    )
    bank = {"mode": "canary", "unitHash": digest(unit.model_dump()), "pre": [], "post": []}
    seen = set()
    for phase in ("pre", "post"):
        questions = getattr(draft, phase)
        if {q.difficulty for q in questions} != {"basic", "intermediate", "advanced"}:
            raise ValueError("Canary exam omitted a level")
        for q in questions:
            if not q.rubric or prompt_key(q.model_dump()) in seen:
                raise ValueError("Invalid canary exam rubric or overlapping prompt")
            seen.add(prompt_key(q.model_dump()))
            bank[phase].append(
                {
                    "id": f"{phase}-{q.difficulty}",
                    "conceptId": concept.id,
                    "question": q.model_dump(),
                }
            )
    pack, _ = generate_grounded(
        preparation,
        "Expert",
        instruction("Expert", "grounded"),
        context,
        DifficultyMaterials,
        unit.chunks(),
    )
    if any(prompt_key(q.model_dump()) in seen for q in pack.tests):
        raise ValueError("Canary teaching/test overlap")
    artifact = {
        "mode": "canary",
        "graph": {"concepts": [concept.model_dump()], "prerequisites": []},
        "materials": {concept.id: {"content": pack.model_dump()}},
    }
    freeze(destination / "private-exams.json", bank)
    freeze(destination / "expert.json", artifact)
    variants = {"expert": "grounded", "tutor": "utility", "assessor": "weighted"}
    result = run_episode(
        unit,
        bank,
        artifact,
        variants,
        "intermediate",
        0,
        "adaptive",
        ExperimentConfig(activities=2, maxCalls=32, maxTokens=150000, model=episode_provider.model),
        episode_provider,
        destination / "episode",
        mode="canary",
    )
    freeze(
        destination / "canary-report.json",
        {
            "mode": "canary",
            "notResearchEvidence": True,
            "result": result,
            "preparationUsage": usage(preparation.calls),
        },
    )
    return result
