"""Built-in prompt metadata and compatibility helpers.

v2 is the single built-in prompt set; legacy v1 references resolve to v2.
"""

VERSIONS = ("v2",)


def prompt_version(services, role):
    del services, role
    return "v2"


def versioned(services, role, v1, v2):
    del services, role, v1
    return v2


def _prompt(title, text, note=""):
    item = {"title": title, "text": text.strip()}
    if note:
        item["note"] = note
    return item


def builtin_prompts(agent, version="v2", variant="baseline"):
    """Built-in prompt text for each template section. Template text is added after these."""
    del version
    from learnloop.agents.assessing import prompts as assessing_prompts
    from learnloop.agents.expert import prompts as expert_prompts
    from learnloop.agents.expert import prompts_variants
    from learnloop.agents.tutoring import prompts as tutoring_prompts

    if agent == "expert":
        organization = prompts_variants.VARIANTS.get(variant, {})
        note = (
            f"Course-structure variant: {variant}."
            if organization
            else "Production course-structure prompt."
        )
        return {
            "analysis": [
                _prompt(
                    title,
                    organization.get(name) or getattr(expert_prompts, name),
                    note
                    if name == "SECTION_PROMPT"
                    else note + " Additional instructions are not appended to this prompt.",
                )
                for title, name in (
                    ("Section concepts", "SECTION_PROMPT"),
                    ("Relationship analyst", "RELATION_PROMPT"),
                    ("Relationship reviewer", "REVIEW_PROMPT"),
                    ("Curriculum plan", "CURRICULUM_PROMPT"),
                )
            ],
            "lesson": [
                _prompt("Course materials", expert_prompts.PYRAMID_MATERIALS_PROMPT),
                _prompt("Pseudo-student tests", expert_prompts.EXPERT_MATERIALS_PROMPT),
            ],
            "questions": [
                _prompt("Single-answer question", expert_prompts.ON_DEMAND_QUESTION_PROMPT),
                _prompt("Mixed-format question", expert_prompts.MIXED_PROMPT),
                _prompt(
                    "Format rules",
                    "\n\n".join(
                        f"{name}\n{text}"
                        for name, text in expert_prompts.FORMAT_INSTRUCTIONS.items()
                    ),
                ),
                _prompt("Answer-key check", expert_prompts.QUESTION_KEY_PROMPT),
                _prompt("Independent solve", expert_prompts.SOLVE_PROMPT),
            ],
        }
    if agent == "tutor":
        return {
            "analysis": [_prompt("Learning plan", tutoring_prompts.PLAN_PROMPT)],
            "lesson": [_prompt("Tutor response", tutoring_prompts.CHAT_PROMPT)],
            "questions": [],
        }
    return {
        "analysis": [_prompt("Multiple-choice assessment", assessing_prompts.FEEDBACK_PROMPT)],
        "lesson": [_prompt("Written answer", assessing_prompts.OPEN_FEEDBACK_PROMPT)],
        "questions": [_prompt("Fill-in blanks", assessing_prompts.BLANK_EQUIVALENCE_PROMPT)],
    }
