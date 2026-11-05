"""Resolve local templates without changing imported backend prompt constants."""

import ast
import importlib
from pathlib import Path

from . import BACKEND


def catalog():
    templates = {}
    modules = {
        "expert": "learnloop.agents.expert.prompts",
        "tutoring": "learnloop.agents.tutoring.prompts",
        "assessing": "learnloop.agents.assessing.prompts",
        "tutoring_chat": "learnloop.agents.tutoring.chat",
        "shared_grounding": "learnloop.agents.grounding",
        "expert_rubric": "learnloop.agents.rubrics",
        "expert_extension": "learnloop.agents.question_review",
    }
    for group, name in modules.items():
        for key, value in vars(importlib.import_module(name)).items():
            if key.endswith("_PROMPT") and isinstance(value, str):
                if key in {"EXAMPLE_STYLE_PROMPT", "POST_STYLE_PROMPT"}:
                    continue  # These fragments are already composed into final templates.
                templates[f"{group}/{key.lower()}"] = value
    # These production prompts are inline literals rather than named constants.
    path = BACKEND / "learnloop/agents/expert/materials.py"
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "generate"
            and len(node.args) >= 4
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and isinstance(node.args[3], ast.Name)
        ):
            templates[f"expert/{node.args[3].id.lower()}"] = node.args[1].value
    return templates


class PromptStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.defaults = catalog()

    def export(self):
        """Create missing templates; never overwrite a teammate's edits."""
        created = []
        for name, text in self.defaults.items():
            path = self.directory / f"{name}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(text, encoding="utf-8")
                created.append(name)
        return created

    def read(self, name):
        if name not in self.defaults:
            raise ValueError(f"Unknown prompt: {name}. Use 'prompts list'.")
        path = self.directory / f"{name}.txt"
        text = (
            path.read_text(encoding="utf-8") if path.exists() else self.defaults[name]
        )
        if not text.strip():
            raise ValueError(f"Prompt is empty: {name}")
        return text

    def resolve(self, instruction):
        # Preserve runtime suffixes used by deduplication and independent reviews.
        for name, original in sorted(
            self.defaults.items(), key=lambda item: len(item[1]), reverse=True
        ):
            if instruction.startswith(original):
                return name, self.read(name) + instruction[len(original) :]
        return None, instruction
