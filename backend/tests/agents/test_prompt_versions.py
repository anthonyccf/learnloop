from types import SimpleNamespace

from learnloop.agents.expert import prompts as expert_prompts
from learnloop.core.prompt_versions import prompt_version, versioned
from learnloop.core.schemas import PyramidMaterials
from learnloop.persistence.database import Document
from learnloop.runtime.worker import work_once
from learnloop.runtime.workflows import PromptConfiguredServices
from tests.api.test_integration import prepare


def configured(version):
    return SimpleNamespace(settings=SimpleNamespace(prompt_version=version))


def test_prompt_version_unifies_on_v2_and_accepts_legacy_inputs():
    assert prompt_version(object(), "Expert") == "v2"
    assert prompt_version(configured("v1"), "Expert") == "v2"
    assert prompt_version(configured("v3"), "Expert") == "v2"
    assert versioned(configured("v1"), "Tutoring", "first", "second") == "second"
    legacy = PromptConfiguredServices(configured("v1"), {"agent": "assessing", "prompts": {}})
    assert prompt_version(legacy, "Assessing") == "v2"


def test_builtin_prompt_endpoint_returns_unified_prompts_for_legacy_and_v2(stack):
    client = stack[0]
    v2 = client.get("/api/agent-templates/builtin-prompts?agent=expert&version=v2").json()
    v1 = client.get("/api/agent-templates/builtin-prompts?agent=expert&version=v1").json()
    assert v2["lesson"][0]["text"] == expert_prompts.PYRAMID_MATERIALS_PROMPT.strip()
    assert v1 == v2
    tutor = client.get("/api/agent-templates/builtin-prompts?agent=tutor").json()
    assert tutor["questions"] == []
    assert "assessment_pending" in tutor["lesson"][0]["text"]


def test_saved_template_round_trips_base_prompts(stack):
    client = stack[0]
    template = {
        "id": "v2-tutor",
        "agent": "tutor",
        "name": "Tutor prompts",
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


def test_legacy_v1_materials_regenerate_as_v2(stack, monkeypatch):
    client, factory, services, _ = stack
    _, upload = prepare(stack)
    with factory.begin() as db:
        doc = db.get(Document, upload["documentId"])
        graph = dict(doc.graph)
        resources = {
            cid: {k: v for k, v in res.items() if k != "promptVersion"}
            for cid, res in graph["resources"].items()
        }
        doc.graph = {**graph, "resources": resources}

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
    assert all(expert_prompts.PYRAMID_MATERIALS_PROMPT in i for i in instructions)
    with factory() as db:
        updated = db.get(Document, upload["documentId"]).graph["resources"]
        assert all(r["promptVersion"] == "v2" for r in updated.values())
