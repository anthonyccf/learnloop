from types import SimpleNamespace

from learnloop.agents.expert import prompts as baseline
from learnloop.agents.expert.prompts_variants import VARIANTS, organization_prompt
from learnloop.runtime.workflows import PromptConfiguredServices

PROMPTS = ("SECTION_PROMPT", "RELATION_PROMPT", "REVIEW_PROMPT", "CURRICULUM_PROMPT")


def configured(variant):
    return SimpleNamespace(settings=SimpleNamespace(organization_prompt_variant=variant))


def test_baseline_and_unknown_variants_use_production_prompts():
    for name in PROMPTS:
        expected = getattr(baseline, name)
        assert organization_prompt(object(), name) == expected
        assert organization_prompt(configured("baseline"), name) == expected
        assert organization_prompt(configured("v9"), name) == expected


def test_each_variant_supplies_distinct_prompts():
    for name in PROMPTS:
        texts = {organization_prompt(configured(v), name) for v in VARIANTS}
        texts.add(getattr(baseline, name))
        assert len(texts) == len(VARIANTS) + 1


def test_expert_template_variant_overrides_setting():
    expert = PromptConfiguredServices(
        configured("rules"), {"agent": "expert", "organizationVariant": "exemplar"}
    )
    legacy = PromptConfiguredServices(configured("rules"), {"agent": "expert", "prompts": {}})
    tutor = PromptConfiguredServices(
        configured("rules"), {"agent": "tutor", "organizationVariant": "exemplar"}
    )
    assert organization_prompt(expert, "SECTION_PROMPT") == VARIANTS["exemplar"]["SECTION_PROMPT"]
    assert organization_prompt(legacy, "SECTION_PROMPT") == VARIANTS["rules"]["SECTION_PROMPT"]
    assert organization_prompt(tutor, "SECTION_PROMPT") == VARIANTS["rules"]["SECTION_PROMPT"]


def test_template_round_trips_variant_and_preview_shows_it(stack):
    client = stack[0]
    template = {
        "id": "procedural-expert",
        "agent": "expert",
        "name": "Procedural structure",
        "prompts": {"analysis": "", "lesson": "", "questions": ""},
        "enabledTools": [],
        "model": "configured",
        "temperature": None,
        "organizationVariant": "procedural",
        "createdAt": "2026-11-18T00:00:00Z",
        "updatedAt": "2026-11-18T00:00:00Z",
    }
    assert client.post("/api/agent-templates/save", json={"template": template}).status_code == 200
    saved = client.get("/api/agent-templates").json()
    assert saved[0]["organizationVariant"] == "procedural"
    url = "/api/agent-templates/builtin-prompts?agent=expert&version=v2"
    preview = client.get(url + "&variant=procedural").json()["analysis"]
    assert [p["text"] for p in preview] == [
        VARIANTS["procedural"][name].strip() for name in PROMPTS
    ]
    default = client.get(url).json()["analysis"]
    assert default[0]["text"] == baseline.SECTION_PROMPT.strip()


def test_variant_survives_template_wrapper():
    wrapped = PromptConfiguredServices(configured("procedural"), {"agent": "expert", "prompts": {}})
    assert (
        organization_prompt(wrapped, "CURRICULUM_PROMPT")
        == VARIANTS["procedural"]["CURRICULUM_PROMPT"]
    )


def test_redeveloped_variants_include_repair_and_fidelity_guardrails():
    for variant, mapping in VARIANTS.items():
        assert "sourceReviewFeedback" in mapping["SECTION_PROMPT"], variant
        assert "rejectedDraft" in mapping["SECTION_PROMPT"], variant
        assert "validationFeedback" in mapping["REVIEW_PROMPT"], variant
        assert "validationFeedback" in mapping["CURRICULUM_PROMPT"], variant
        assert "proposedPlan" in mapping["CURRICULUM_PROMPT"], variant
        assert "teaches" in mapping["CURRICULUM_PROMPT"], variant

