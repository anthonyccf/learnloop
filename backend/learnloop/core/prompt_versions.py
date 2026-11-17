"""Select between built-in prompt versions.

A matching agent template's basePrompts wins; otherwise PROMPT_VERSION applies.
"""

VERSIONS = ("v1", "v2")


def prompt_version(services, role):
    chooser = getattr(services, "template_prompt_version", None)
    version = chooser(role) if callable(chooser) else None
    if version not in VERSIONS:
        version = getattr(getattr(services, "settings", None), "prompt_version", "v1")
    return version if version in VERSIONS else "v1"


def versioned(services, role, v1, v2):
    return v2 if prompt_version(services, role) == "v2" else v1


def _prompt(title, text, note=""):
    item = {"title": title, "text": text.strip()}
    if note:
        item["note"] = note
    return item


def builtin_prompts(agent, version):
    """Built-in prompt text for each template section. Template text is added after these."""
    from learnloop.agents.assessing import mixed_answers as assessing_mixed
    from learnloop.agents.assessing import prompts as assessing_v1
    from learnloop.agents.assessing import prompts_v2 as assessing_v2
    from learnloop.agents.expert import prompts as expert_v1
    from learnloop.agents.expert import prompts_v2 as expert_v2
    from learnloop.agents.expert import questions as expert_questions
    from learnloop.agents.tutoring import chat as tutoring_chat
    from learnloop.agents.tutoring import prompts as tutoring_v1
    from learnloop.agents.tutoring import prompts_v2 as tutoring_v2

    if agent == "expert":
        current = expert_v2 if version == "v2" else expert_v1
        formats = (
            current.FORMAT_INSTRUCTIONS if version == "v2" else expert_questions.FORMAT_INSTRUCTIONS
        )
        mixed = current.MIXED_PROMPT if version == "v2" else expert_questions.MIXED_PROMPT
        solve = current.SOLVE_PROMPT if version == "v2" else expert_questions.SOLVE_PROMPT
        return {
            "analysis": [
                _prompt(
                    "Section concepts",
                    expert_v1.SECTION_PROMPT,
                    "Shared by v1 and v2. v2 changes the lesson and question prompts.",
                )
            ],
            "lesson": [
                _prompt("Course materials", current.PYRAMID_MATERIALS_PROMPT),
                _prompt("Pseudo-student tests", current.EXPERT_MATERIALS_PROMPT),
            ],
            "questions": [
                _prompt("Single-answer question", current.ON_DEMAND_QUESTION_PROMPT),
                _prompt("Mixed-format question", mixed),
                _prompt(
                    "Format rules",
                    "\n\n".join(f"{name}\n{text}" for name, text in formats.items()),
                ),
                _prompt("Answer-key check", current.QUESTION_KEY_PROMPT),
                _prompt("Independent solve", solve),
            ],
        }
    if agent == "tutor":
        current = tutoring_v2 if version == "v2" else tutoring_v1
        return {
            "analysis": [_prompt("Learning plan", current.PLAN_PROMPT)],
            "lesson": [
                _prompt(
                    "Tutor response",
                    current.CHAT_PROMPT if version == "v2" else tutoring_chat.CHAT_PROMPT,
                )
            ],
            "questions": [],
        }
    current = assessing_v2 if version == "v2" else assessing_v1
    return {
        "analysis": [_prompt("Multiple-choice assessment", current.FEEDBACK_PROMPT)],
        "lesson": [
            _prompt(
                "Written answer",
                assessing_v2.OPEN_FEEDBACK_PROMPT
                if version == "v2"
                else assessing_mixed.OPEN_FEEDBACK_PROMPT,
            )
        ],
        "questions": [
            _prompt(
                "Fill-in blanks",
                assessing_v2.BLANK_EQUIVALENCE_PROMPT
                if version == "v2"
                else assessing_mixed.BLANK_EQUIVALENCE_PROMPT,
            )
        ],
    }
