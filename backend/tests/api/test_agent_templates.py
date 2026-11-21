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


def test_tutor_run_applies_the_expert_template_to_expert_calls():
    class Services:
        settings = None

        def generate(self, role, instruction, context, output, **kwargs):
            return instruction, kwargs

    class Question:
        pass

    class FillInQuestion:
        pass

    class PostLesson:
        pass

    class PlanChoice:
        pass

    tutor = template("tutor-1", "tutor")
    tutor["prompts"]["analysis"] = "Plan this"
    expert = template("expert-1")
    expert["prompts"]["questions"] = "Ask this way"
    expert["prompts"]["lesson"] = "Teach this way"
    expert["model"] = "expert-model"
    expert["temperature"] = 0.1
    expert["organizationVariant"] = "rules"
    service = PromptConfiguredServices(Services(), tutor, expert_template=expert)
    instruction, options = service.generate("Expert", "base", {}, Question)
    assert "Ask this way" in instruction and "Plan this" not in instruction
    assert options["model"] == "expert-model" and options["temperature"] == 0.1
    instruction, _ = service.generate("Expert", "base", {}, FillInQuestion)
    assert "Ask this way" in instruction
    instruction, _ = service.generate("Expert", "base", {}, PostLesson)
    assert "Teach this way" in instruction and "Ask this way" not in instruction
    instruction, options = service.generate("Tutoring", "base", {}, PlanChoice)
    assert "Plan this" in instruction and "Ask this way" not in instruction
    assert options["model"] is None
    assert service.template_organization_variant() == "rules"
