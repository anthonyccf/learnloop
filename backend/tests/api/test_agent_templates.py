from learnloop.persistence.database import Course, Run
from learnloop.runtime.events import new_run
from learnloop.runtime.workflows import PromptConfiguredServices
from learnloop.core.schemas import DocumentAnalyzeRequest
from learnloop.api.routes.workbench_tutor import Start


def template(id, agent="expert", default=False):
    return {"id": id, "agent": agent, "name": id, "prompts": {"analysis": "analyse", "lesson": "teach", "questions": "test"}, "enabledTools": [], "model": "configured", "temperature": None, "createdAt": "2026-01-01", "updatedAt": "2026-01-01", "isDefault": default}


def test_v2_builtin_only_templates_are_valid_and_keep_version():
    from types import SimpleNamespace
    base = {"id": "v2", "name": "v2", "prompts": {"analysis": "", "lesson": "", "questions": ""}, "model": "configured", "basePrompts": "v2"}
    expert = DocumentAnalyzeRequest.model_validate({"promptTemplate": {**base, "agent": "expert"}}).promptTemplate
    tutor = Start.model_validate({"mode": "lesson", "promptTemplate": {**base, "agent": "tutor"}}).promptTemplate
    assert expert.model_dump()["basePrompts"] == "v2"
    assert tutor.model_dump()["basePrompts"] == "v2"
    service = SimpleNamespace(settings=None)
    assert PromptConfiguredServices(service, expert.model_dump()).template_prompt_version("Expert") == "v2"
    assert PromptConfiguredServices(service, tutor.model_dump()).template_prompt_version("Tutoring") == "v2"


def test_shared_templates_defaults_import_and_snapshot(stack):
    client, factory, _, _ = stack
    first = template("first", default=True)
    second = template("second", default=True)
    assert client.post("/api/agent-templates/save", json={"template": first}).status_code == 200
    assert client.post("/api/agent-templates/save", json={"template": second}).status_code == 200
    records = client.get("/api/agent-templates").json()
    assert {x["id"]: x["isDefault"] for x in records} == {"first": False, "second": True}
    assert client.post("/api/agent-templates/save", json={"template": first, "importOnly": True}).status_code == 200
    with factory.begin() as db:
        course = Course(owner_id="test-owner", title="Course")
        db.add(course)
        db.flush()
        run = new_run(db, course, "course_preparation", {})
        run_id = run.id
    assert client.post("/api/agent-templates/delete", json={"id": "second"}).status_code == 200
    with factory() as db:
        assert db.get(Run, run_id).input["prompt_template"]["id"] == "second"
    assert client.get("/api/agent-templates").json()[0]["isDefault"] is False


def test_assessing_template_only_changes_assessing_calls():
    class Services:
        settings = None
        def generate(self, role, instruction, context, output, **kwargs):
            return instruction, kwargs
    class Assessment: pass
    service = PromptConfiguredServices(Services(), template("review", "assessing"))
    instruction, options = service.generate("Assessing", "base", {}, Assessment)
    assert "analyse" in instruction and "teach" in instruction and "test" in instruction
    assert "model" in options
    instruction, options = service.generate("Expert", "base", {}, Assessment)
    assert instruction == "base" and not options
