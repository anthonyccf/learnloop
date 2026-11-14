"""Export the strict model output schemas used by the agent workbench."""

import json
from pathlib import Path

from learnloop.agents.assessing.mixed_answers import BlankEquivalence
from learnloop.core.question_formats import QUESTION_MODELS
from learnloop.core.schemas import (
    Assessment,
    PlanChoice,
    PyramidMaterials,
    SectionGraph,
    TutorChatReply,
)


def strict(schema):
    """Apply the same strict-object rules as Services.generate."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
            schema["required"] = list(schema.get("properties", {}))
        for value in schema.values():
            strict(value)
    elif isinstance(schema, list):
        for value in schema:
            strict(value)


def main():
    models = {
        "expert.analysis": {"SectionGraph": SectionGraph},
        "expert.lesson": {"PyramidMaterials": PyramidMaterials},
        "expert.questions": {name: model for name, model in QUESTION_MODELS.items()},
        "tutor.analysis": {"PlanChoice": PlanChoice},
        "tutor.lesson": {"TutorChatReply": TutorChatReply},
        "tutor.questions": {},
        "assessing.analysis": {"Assessment": Assessment, "BlankEquivalence": BlankEquivalence},
        "assessing.lesson": {"Assessment": Assessment},
        "assessing.questions": {},
    }
    result = {}
    for stage, options in models.items():
        result[stage] = {}
        for name, model in options.items():
            schema = model.model_json_schema()
            strict(schema)
            result[stage][name] = schema

    destination = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "agent-output-schemas.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
