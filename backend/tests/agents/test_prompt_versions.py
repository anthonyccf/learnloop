from types import SimpleNamespace

from learnloop.agents.expert import prompts as expert_v1
from learnloop.agents.expert import prompts_v2 as expert_v2
from learnloop.core.prompt_versions import prompt_version, versioned
from learnloop.core.schemas import PyramidMaterials
from learnloop.persistence.database import Document
from learnloop.runtime.worker import work_once
from learnloop.runtime.workflows import PromptConfiguredServices
from tests.api.test_integration import prepare


def configured(version):
    return SimpleNamespace(settings=SimpleNamespace(prompt_version=version))


def test_template_base_prompts_apply_only_to_its_role():
    assert prompt_version(object(), "Expert") == "v1"
    assert prompt_version(configured("v3"), "Expert") == "v1"
    assert versioned(configured("v2"), "Tutoring", "first", "second") == "second"
    tutor = PromptConfiguredServices(configured("v1"), {"agent": "tutor", "basePrompts": "v2"})
    assert prompt_version(tutor, "Tutoring") == "v2"
    assert prompt_version(tutor, "Expert") == prompt_version(tutor, "Assessing") == "v1"
    legacy = PromptConfiguredServices(configured("v1"), {"agent": "assessing", "prompts": {}})
    assert prompt_version(legacy, "Assessing") == "v1"


def test_builtin_prompt_endpoint_returns_the_selected_version(stack):
    client = stack[0]
    v2 = client.get("/api/agent-templates/builtin-prompts?agent=expert&version=v2").json()
    v1 = client.get("/api/agent-templates/builtin-prompts?agent=expert&version=v1").json()
    assert v2["lesson"][0]["text"] == expert_v2.PYRAMID_MATERIALS_PROMPT.strip()
    assert v1["lesson"][0]["text"] == expert_v1.PYRAMID_MATERIALS_PROMPT.strip()
    assert v2["lesson"][0]["text"] != v1["lesson"][0]["text"]
    tutor = client.get("/api/agent-templates/builtin-prompts?agent=tutor&version=v2").json()
    assert tutor["questions"] == []
    assert "assessment_pending" in tutor["lesson"][0]["text"]


def test_saved_template_round_trips_base_prompts(stack):
    client = stack[0]
    template = {
        "id": "v2-tutor",
        "agent": "tutor",
        "name": "Tutor v2 prompts",
        "prompts": {"analysis": "", "lesson": "", "questions": ""},
        "enabledTools": [],
        "model": "configured",
        "temperature": None,
        "basePrompts": "v2",
        "createdAt": "2026-11-16T00:00:00Z",
        "updatedAt": "2026-11-16T00:00:00Z",
    }
    assert client.post("/api/agent-templates/save", json={"template": template}).status_code == 200
    saved = client.get("/api/agent-templates").json()
    assert saved[0]["basePrompts"] == "v2"


def test_switching_to_v2_regenerates_and_tags_materials(stack, monkeypatch):
    client, factory, services, settings = stack
    services.settings = settings.model_copy(update={"prompt_version": "v1"})
    _, upload = prepare(stack)
    with factory() as db:
        resources = db.get(Document, upload["documentId"]).graph["resources"]
        assert resources and all("promptVersion" not in r for r in resources.values())

    services.settings = settings.model_copy(update={"prompt_version": "v2"})
    instructions = []
    generate = services.generate

    def tracked(role, instruction, context, output):
        if output is PyramidMaterials:
            instructions.append(instruction)
        return generate(role, instruction, context, output)

    monkeypatch.setattr(services, "generate", tracked)
    receipt = client.post(f"/api/documents/{upload['documentId']}/materials").json()
    assert work_once(factory, services)
    run = client.get(f"/api/agent-activity/runs/{receipt['runId']}").json()
    assert run["status"] == "completed"
    assert len(instructions) == len(resources)
    assert all(expert_v2.PYRAMID_MATERIALS_PROMPT in i for i in instructions)
    assert not any(expert_v1.PYRAMID_MATERIALS_PROMPT in i for i in instructions)
    with factory() as db:
        updated = db.get(Document, upload["documentId"]).graph["resources"]
        assert all(r["promptVersion"] == "v2" for r in updated.values())
