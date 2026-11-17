from pydantic import SecretStr

from learnloop import evaluation_workbench_job
from learnloop.api.routes import evaluations
from learnloop.evaluation.artifacts import digest, freeze, thaw
from learnloop.persistence.database import AgentTemplate, Course, CourseRelease, Document
from learnloop.persistence.releases import fingerprint


def test_readiness_blocks_launch_without_creating_a_job(stack, monkeypatch, tmp_path):
    client, _, _, _ = stack
    monkeypatch.setattr(evaluations, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(
        evaluations,
        "readiness",
        lambda *args, **kwargs: {
            "ready": False,
            "blockers": ["Human review pending"],
            "reviews": {},
            "modelChecked": True,
        },
    )
    response = client.get("/api/evaluations/bundles")
    assert response.json()[0]["readiness"]["blockers"] == ["Human review pending"]
    response = client.post("/api/evaluations/runs", json={"bundle": evaluations.BUNDLE_ID})
    assert response.status_code == 409
    assert not evaluations.RUNS.exists()


def test_run_creation_validates_inputs_and_is_owner_scoped(stack, monkeypatch, tmp_path):
    client, _, _, settings = stack
    settings.llm_api_key = SecretStr("test-key")
    monkeypatch.setattr(evaluations, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(evaluations, "readiness", lambda *args, **kwargs: {"ready": True})
    launched = []
    monkeypatch.setattr(
        evaluations.subprocess, "Popen", lambda args, **kwargs: launched.append(args)
    )
    assert client.post("/api/evaluations/runs", json={"bundle": "../../other"}).status_code == 422
    assert (
        client.post(
            "/api/evaluations/runs", json={"bundle": evaluations.BUNDLE_ID, "repeats": 100}
        ).status_code
        == 422
    )
    response = client.post(
        "/api/evaluations/runs", json={"bundle": evaluations.BUNDLE_ID, "baselines": True}
    )
    assert response.status_code == 202
    run = response.json()
    assert run["settings"]["baselines"] is True and run["status"] == "starting"
    assert len(launched) == 1
    assert client.get("/api/evaluations/runs/" + run["id"]).status_code == 200
    settings.local_owner_id = "another-owner"
    assert client.get("/api/evaluations/runs/" + run["id"]).status_code == 404


def test_job_passes_settings_to_harness_and_records_failure(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    settings = evaluations.StartEvaluation(bundle=evaluations.BUNDLE_ID, baselines=True)
    (tmp_path / "job.json").write_text(
        json.dumps({"settings": settings.model_dump(), "model": "model-version"}), encoding="utf-8"
    )
    monkeypatch.setattr(evaluation_workbench_job.sys, "argv", ["job", str(tmp_path)])
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(evaluation_workbench_job.subprocess, "run", fake_run)
    evaluation_workbench_job.main()
    assert "--baselines" in calls[0][0]
    assert calls[0][1]["env"]["OPENROUTER_MODEL"] == "model-version"
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["status"] == "failed"


def test_setup_pins_published_material_and_template_snapshot(stack, monkeypatch, tmp_path):
    client, factory, _, settings = stack
    monkeypatch.setattr(evaluations, "RUNS", tmp_path / "runs")
    with factory.begin() as db:
        course = Course(owner_id="test-owner", title="Course")
        db.add(course)
        db.flush()
        document = Document(
            course_id=course.id,
            filename="notes.txt",
            sha256="a" * 64,
            content_type="text/plain",
            content=b"notes",
            status="published",
        )
        db.add(document)
        db.flush()
        payload = {
            "documents": [
                {
                    "id": document.id,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "graph": {"concepts": [{"id": "one"}]},
                }
            ]
        }
        release = CourseRelease(
            course_id=course.id, version=1, sha256=fingerprint(payload), payload=payload
        )
        template = AgentTemplate(
            id="template-1",
            owner_id="test-owner",
            agent="tutor",
            data={"name": "First", "prompts": {"analysis": "Original"}},
        )
        db.add_all([release, template])
        course_id, document_id = course.id, document.id
    response = client.post(
        "/api/evaluations/setups",
        json={"courseId": course_id, "documentId": document_id, "tutorTemplateId": "template-1"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "configuration_saved"
    with factory.begin() as db:
        db.get(AgentTemplate, "template-1").data = {"name": "Changed"}
    saved = client.get("/api/evaluations/setups").json()
    assert saved[0]["templates"]["tutor"]["prompts"]["analysis"] == "Original"
    assert saved[0]["release"]["version"] == 1
    assert len(saved[0]["learners"]) == 4
    custom = client.post(
        "/api/evaluations/learners",
        json={
            "name": "My learner",
            "model": "configured",
            "basic": 0.5,
            "intermediate": 0.3,
            "advanced": 0.1,
            "hint": 0.2,
            "gain": 0.05,
            "delaySeconds": 20,
        },
    ).json()
    custom_setup = client.post(
        "/api/evaluations/setups",
        json={
            "courseId": course_id,
            "documentId": document_id,
            "learnerProfileIds": [custom["id"]],
        },
    )
    assert custom_setup.status_code == 201
    assert custom_setup.json()["learners"][0] == custom
    settings.llm_api_key = SecretStr("test-key")
    monkeypatch.setattr(evaluations, "_pseudo_root", lambda owner: tmp_path / owner)
    launched = []
    monkeypatch.setattr(
        evaluations.subprocess, "Popen", lambda args, **kwargs: launched.append(args)
    )
    started = client.post(
        "/api/evaluations/pseudo-runs",
        json={"setupId": custom_setup.json()["id"], "concepts": 1, "activities": 2},
    )
    assert started.status_code == 202
    assert started.json()["learnerCount"] == 1 and len(launched) == 1
    assert len(client.get("/api/evaluations/pseudo-runs").json()) == 1
    source_path = tmp_path / "test-owner" / started.json()["id"]
    for name in ("unit.json", "exams.json", "expert.json"):
        freeze(source_path / name, {"fixture": name})
    reused = client.post(
        "/api/evaluations/pseudo-runs",
        json={"setupId": custom_setup.json()["id"], "sourceRunId": started.json()["id"]},
    )
    assert reused.status_code == 202
    reused_input = thaw(tmp_path / "test-owner" / reused.json()["id"] / "input.json")["payload"]
    assert reused_input["reused"]["expert"] == {"fixture": "expert.json"}
    (source_path / "status.json").write_text(
        '{"status":"completed_with_failures"}', encoding="utf-8"
    )
    freeze(source_path / "report.json", {"fixture": True})
    episode = source_path / "episodes" / digest([custom["id"], "adaptive"])[:16]
    freeze(episode / "result.json", {"status": "failed", "errorType": "ValueError"})
    monkeypatch.setattr(evaluations, "retry_inputs", lambda *args: None)
    retry = client.post(
        f"/api/evaluations/pseudo-runs/{started.json()['id']}/retry",
        json={"learnerId": custom["id"], "condition": "adaptive"},
    )
    assert retry.status_code == 202 and retry.json()["attempt"] == 2
    assert thaw(episode / "result.json")["payload"]["status"] == "failed"
    assert (
        client.post(
            f"/api/evaluations/pseudo-runs/{started.json()['id']}/retry",
            json={"learnerId": custom["id"], "condition": "adaptive"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/evaluations/pseudo-runs",
            json={"setupId": custom_setup.json()["id"], "sourceRunId": "f" * 32},
        ).status_code
        == 409
    )
    different = tmp_path / "test-owner" / ("e" * 32)
    bad_setup = custom_setup.json()
    bad_setup["material"]["id"] = "different-material"
    freeze(different / "input.json", {"setup": bad_setup})
    for name in ("unit.json", "exams.json", "expert.json"):
        freeze(different / name, {"fixture": name})
    assert (
        client.post(
            "/api/evaluations/pseudo-runs",
            json={"setupId": custom_setup.json()["id"], "sourceRunId": "e" * 32},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/evaluations/setups",
            json={
                "courseId": course_id,
                "documentId": document_id,
                "learnerProfileIds": ["missing"],
            },
        ).status_code
        == 422
    )
    settings.local_owner_id = "other-owner"
    assert client.get("/api/evaluations/setups").json() == []
    assert (
        client.post(
            "/api/evaluations/setups", json={"courseId": course_id, "documentId": document_id}
        ).status_code
        == 404
    )


def test_custom_learner_creation_validation_and_owner_isolation(stack, monkeypatch, tmp_path):
    client, _, _, settings = stack
    monkeypatch.setattr(evaluations, "RUNS", tmp_path / "runs")
    profile = {
        "name": "Careful learner",
        "model": "provider/model",
        "basic": 0.5,
        "intermediate": 0.3,
        "advanced": 0.1,
        "hint": 0.7,
        "gain": 0.08,
        "delaySeconds": 30,
        "misconceptions": True,
    }
    assert len(client.get("/api/evaluations/learners").json()) == 4
    assert (
        client.post("/api/evaluations/learners", json={**profile, "gain": 0.2}).status_code == 422
    )
    response = client.post("/api/evaluations/learners", json=profile)
    assert response.status_code == 201
    saved = response.json()
    assert saved["name"] == profile["name"] and saved["model"] == profile["model"]
    assert saved["builtin"] is False
    assert any(item["id"] == saved["id"] for item in client.get("/api/evaluations/learners").json())
    settings.local_owner_id = "other-owner"
    assert all(item["id"] != saved["id"] for item in client.get("/api/evaluations/learners").json())


def test_all_material_setup_pins_full_release_and_requires_coverage(stack, monkeypatch, tmp_path):
    client, factory, _, settings = stack
    monkeypatch.setattr(evaluations, "RUNS", tmp_path / "runs")
    with factory.begin() as db:
        course = Course(owner_id="test-owner", title="Two files")
        db.add(course)
        db.flush()
        docs = [
            Document(
                course_id=course.id,
                filename=f"{i}.txt",
                sha256=str(i) * 64,
                content_type="text/plain",
                content=b"text",
                status="published",
            )
            for i in (1, 2)
        ]
        db.add_all(docs)
        db.flush()
        payload = {
            "documents": [
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "sha256": doc.sha256,
                    "graph": {"concepts": [{"id": f"c{i}"}]},
                }
                for i, doc in enumerate(docs)
            ]
        }
        db.add(
            CourseRelease(
                course_id=course.id, version=1, sha256=fingerprint(payload), payload=payload
            )
        )
        course_id = course.id
    response = client.post(
        "/api/evaluations/setups", json={"courseId": course_id, "documentId": "__all__"}
    )
    assert response.status_code == 201
    setup = response.json()
    assert setup["material"]["id"] == "__all__" and setup["material"]["documentCount"] == 2
    assert len(setup["material"]["sha256"]) == 64
    settings.llm_api_key = SecretStr("test-key")
    started = client.post(
        "/api/evaluations/pseudo-runs", json={"setupId": setup["id"], "concepts": 1}
    )
    assert started.status_code == 422 and "at least 2" in started.json()["detail"]
