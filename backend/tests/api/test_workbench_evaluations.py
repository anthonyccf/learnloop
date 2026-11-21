from pydantic import SecretStr

from learnloop import evaluation_workbench_job
from learnloop.api.routes import evaluations
from learnloop.evaluation.artifacts import digest, freeze, thaw
from learnloop.persistence.database import AgentTemplate, Course, CourseRelease, Document
from learnloop.persistence.releases import fingerprint


def test_start_from_files_generates_material_and_runs_the_selected_test(stack, monkeypatch, tmp_path_factory):
    from functools import partial

    from learnloop import pseudo_experiment, pseudo_experiment_job
    from learnloop.persistence import database
    from learnloop.runtime.worker import work_once
    from tests.conftest import COURSE_TEXT
    from tests.evaluation.test_pseudo_experiment import OfflineProvider

    client, factory, services, settings = stack
    settings.llm_api_key = SecretStr("test-key")
    root = tmp_path_factory.mktemp("ps")
    monkeypatch.setattr(evaluations, "_pseudo_root", lambda owner: root)
    monkeypatch.setattr(evaluations, "RUNS", root / "workspace")
    launches = []
    monkeypatch.setattr(evaluations, "_launch_test", launches.append)
    monkeypatch.setattr(database, "session_factory", lambda: factory)
    monkeypatch.setattr(pseudo_experiment_job, "get_settings", lambda: settings)
    monkeypatch.setattr(pseudo_experiment, "run", partial(pseudo_experiment.run, provider_cls=OfflineProvider))
    course = client.post("/api/courses", json={"title": "Test course"}).json()["id"]
    material = client.post(
        f"/api/courses/{course}/documents", data={"defer_processing": "true"},
        files={"file": ("notes.txt", COURSE_TEXT.encode(), "text/plain")},
    ).json()["documentId"]
    body = {"courseId": course, "documentIds": [material], "learnerProfileIds": ["novice"], "activities": 3}
    endpoint = "/api/evaluations/pseudo-runs/from-files"
    result = client.post(endpoint, json=body)
    assert result.status_code == 202, result.text
    job = result.json()
    assert job["phase"] == "Generating course materials"
    assert client.post(endpoint, json=body).status_code == 409
    assert len(launches) == 1
    assert work_once(factory, services)
    monkeypatch.setattr(pseudo_experiment_job.sys, "argv", ["job", str(launches[0])])
    pseudo_experiment_job.main()
    view = client.get("/api/evaluations/pseudo-runs").json()[0]
    assert view["status"] == "completed", view
    assert view["report"]["completed"] == 1
    assert view["config"]["activities"] == 3
    assert view["materialId"] == material
    assert view["releaseId"].startswith(f"workbench:{job['workbenchRunId']}:")
    assert client.get("/api/evaluations/setups").json()[0]["id"] == job["setupId"]


def test_stop_during_generation_stops_the_linked_workbench_run(stack, monkeypatch, tmp_path):
    client, _, _, settings = stack
    settings.llm_api_key = SecretStr("test-key")
    monkeypatch.setattr(evaluations, "_pseudo_root", lambda owner: tmp_path / owner)
    monkeypatch.setattr(evaluations, "_launch_test", lambda path: None)
    monkeypatch.setattr(evaluations, "terminate", lambda path: None)
    course = client.post("/api/courses", json={"title": "Stop test"}).json()["id"]
    material = client.post(
        f"/api/courses/{course}/documents", data={"defer_processing": "true"},
        files={"file": ("notes.txt", b"Source material", "text/plain")},
    ).json()["documentId"]
    job = client.post(
        "/api/evaluations/pseudo-runs/from-files",
        json={"courseId": course, "documentIds": [material]},
    ).json()
    result = client.post(f"/api/evaluations/pseudo-runs/{job['id']}/stop")
    assert result.json()["status"] == "stopped"
    assert client.get(f"/api/agent-activity/runs/{job['workbenchRunId']}").json()["status"] == "stopped"


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
    from uuid import uuid4

    from learnloop.core.schemas import DifficultyMaterials
    from learnloop.evaluation.fixtures import FixtureProvider
    from learnloop.persistence.database import Chunk, Run, RunHierarchy

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
        db.add(Document(
            course_id=course.id, filename="draft.txt", sha256="b" * 64,
            content_type="text/plain", content=b"draft", status="uploaded",
        ))
        db.flush()
        text = "Subtract the gradient to reduce the loss. The learning rate controls the update step size."
        concept = {
            "id": "one", "title": "Gradient", "summary": "Understand a gradient update.",
            "sources": [{"chunkId": "one-chunk", "quote": text}],
        }
        prepared = FixtureProvider().generate(
            "Expert", "",
            {"concept": concept, "passages": [{"chunkId": "one-chunk", "text": text}]},
            DifficultyMaterials,
        )
        payload = {
            "documents": [
                {
                    "id": document.id,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "graph": {
                        "concepts": [concept],
                        "resources": {
                            "one": {
                                "lesson": prepared.lesson.as_lesson(),
                                "tests": [q.model_dump() for q in prepared.tests if q.difficulty == "basic"],
                            }
                        },
                    },
                }
            ],
            "graph": {"concepts": [concept], "prerequisites": []},
            "chunks": {"one-chunk": {"text": text, "page": 1, "label": document.filename}},
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
        run_id = str(uuid4())
        db.add_all([
            release,
            template,
            Chunk(
                id="one-chunk", course_id=course.id, document_id=document.id,
                ordinal=0, page=1, text=text,
            ),
            Run(
                id=run_id, course_id=course.id, owner_id="test-owner",
                input={"hierarchy_revision": 1, "hierarchy_ready": True},
                snapshot={"workflow": "course_preparation", "status": "completed"},
            ),
            RunHierarchy(
                run_id=run_id, ready=True,
                graph={"concepts": [concept], "prerequisites": [], "topics": [], "related": []},
                documents=payload["documents"],
            ),
        ])
        course_id, document_id = course.id, document.id
    response = client.post(
        "/api/evaluations/setups",
        json={
            "courseId": course_id,
            "documentId": document_id,
            "workbenchRunId": run_id,
            "tutorTemplateId": "template-1",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "configuration_saved"
    course_detail = client.get(f"/api/courses/{course_id}").json()
    assert course_detail["publishedMaterials"] == [{"id": document_id, "filename": "notes.txt"}]
    assert {d["filename"] for d in course_detail["documents"]} == {"notes.txt", "draft.txt"}
    stale = client.post(
        "/api/evaluations/setups",
        json={"courseId": course_id, "documentId": document_id, "workbenchRunId": str(uuid4())},
    )
    assert stale.status_code == 404
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
            "workbenchRunId": run_id,
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
    assert started.json()["materialSource"] == "workbench_generated"
    assert started.json()["releaseVersion"] == 1
    assert len(client.get("/api/evaluations/pseudo-runs").json()) == 1
    source_path = tmp_path / "test-owner" / started.json()["id"]
    for name in ("unit.json", "exams.json", "expert.json"):
        freeze(source_path / name, {"fixture": name, "materialSource": "workbench_generated"})
    reused = client.post(
        "/api/evaluations/pseudo-runs",
        json={"setupId": custom_setup.json()["id"], "sourceRunId": started.json()["id"]},
    )
    assert reused.status_code == 202
    assert reused.json()["materialSource"] == "workbench_generated"
    reused_input = thaw(tmp_path / "test-owner" / reused.json()["id"] / "input.json")["payload"]
    assert reused_input["reused"]["expert"] == {
        "fixture": "expert.json", "materialSource": "workbench_generated"
    }
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
                "workbenchRunId": run_id,
                "learnerProfileIds": ["missing"],
            },
        ).status_code
        == 422
    )
    settings.local_owner_id = "other-owner"
    assert client.get("/api/evaluations/setups").json() == []
    assert (
        client.post(
            "/api/evaluations/setups",
            json={"courseId": course_id, "documentId": document_id, "workbenchRunId": run_id},
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
    from uuid import uuid4

    from learnloop.persistence.database import Run, RunHierarchy

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
                status="prepared",
            )
            for i in (1, 2)
        ]
        db.add_all(docs)
        db.flush()
        documents = [
            {
                "id": doc.id,
                "filename": doc.filename,
                "sha256": doc.sha256,
                "graph": {"concepts": [{"id": f"c{i}"}]},
            }
            for i, doc in enumerate(docs)
        ]
        run_id = str(uuid4())
        db.add_all([
            Run(
                id=run_id, course_id=course.id, owner_id="test-owner",
                input={"hierarchy_revision": 1, "hierarchy_ready": True},
                snapshot={"workflow": "course_preparation", "status": "completed"},
            ),
            RunHierarchy(
                run_id=run_id, ready=True,
                graph={"concepts": [{"id": "c0"}, {"id": "c1"}], "prerequisites": []},
                documents=documents,
            ),
        ])
        course_id = course.id
    response = client.post(
        "/api/evaluations/setups",
        json={"courseId": course_id, "documentId": "__all__", "workbenchRunId": run_id},
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


def test_stop_pseudo_run_ends_a_running_test(stack, monkeypatch, tmp_path):
    import json
    from pathlib import Path

    client, _, _, _ = stack
    monkeypatch.setattr(evaluations, "_pseudo_root", lambda owner: tmp_path)
    run_id = "ab" * 16
    path = tmp_path / run_id
    path.mkdir()
    (path / "job.json").write_text(
        json.dumps(
            {
                "id": run_id,
                "createdAt": "2026-11-20T00:00:00+00:00",
                "course": "Course",
                "material": "notes.txt",
                "config": {"baselines": False, "concepts": 1, "activities": 2},
            }
        ),
        encoding="utf-8",
    )
    (path / "status.json").write_text(
        '{"status":"running","phase":"Testing Novice"}', encoding="utf-8"
    )
    killed = []
    monkeypatch.setattr(evaluations, "terminate", lambda run: killed.append(Path(run)))
    response = client.post(f"/api/evaluations/pseudo-runs/{run_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "stopped"
    assert body["message"].startswith("You stopped")
    assert killed == [path]
    assert (path / "stop.request").is_file()
    assert client.post(f"/api/evaluations/pseudo-runs/{run_id}/stop").status_code == 409


def test_workbench_generation_is_the_only_material_source(stack, monkeypatch, tmp_path):
    from uuid import uuid4

    from learnloop.core.schemas import DifficultyMaterials
    from learnloop.evaluation.fixtures import FixtureProvider
    from learnloop.persistence.database import Chunk, Run, RunHierarchy

    client, factory, _, settings = stack
    monkeypatch.setattr(evaluations, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(evaluations, "_pseudo_root", lambda owner: tmp_path / "pseudo" / owner)
    settings.llm_api_key = SecretStr("test-key")
    launched = []
    monkeypatch.setattr(
        evaluations.subprocess, "Popen", lambda args, **kwargs: launched.append(args)
    )

    text_one = (
        "Subtract the gradient to reduce the loss. The learning rate controls the update step size."
    )
    text_two = "Paged attention allocates fixed-size KV blocks dynamically to avoid waste."
    fixture = FixtureProvider()

    with factory.begin() as db:
        course = Course(owner_id="test-owner", title="Combined course")
        db.add(course)
        db.flush()
        doc_pub = Document(
            course_id=course.id,
            filename="lec1.pdf",
            sha256="1" * 64,
            content_type="application/pdf",
            content=b"%PDF-1",
            status="published",
        )
        doc_gen = Document(
            course_id=course.id,
            filename="lec2.pdf",
            sha256="2" * 64,
            content_type="application/pdf",
            content=b"%PDF-2",
            status="prepared",
        )
        db.add_all([doc_pub, doc_gen])
        db.flush()
        chunk_pub = Chunk(
            id="chunk-pub",
            course_id=course.id,
            document_id=doc_pub.id,
            ordinal=0,
            page=1,
            text=text_one,
        )
        chunk_gen = Chunk(
            id="chunk-gen",
            course_id=course.id,
            document_id=doc_gen.id,
            ordinal=0,
            page=1,
            text=text_two,
        )
        db.add_all([chunk_pub, chunk_gen])
        db.flush()

        concept_pub = {
            "id": f"{doc_pub.id}:gradient",
            "title": "Gradient update",
            "summary": "Subtract the gradient.",
            "sources": [{"chunkId": "chunk-pub", "quote": text_one}],
        }
        concept_gen = {
            "id": f"{doc_gen.id}:paged-kv",
            "title": "Paged KV cache",
            "summary": "Allocate fixed-size KV blocks.",
            "sources": [{"chunkId": "chunk-gen", "quote": text_two}],
        }
        pack_pub = fixture.generate(
            "Expert",
            "",
            {"concept": concept_pub, "passages": [{"chunkId": "chunk-pub", "text": text_one}]},
            DifficultyMaterials,
        )
        pack_gen = fixture.generate(
            "Expert",
            "",
            {"concept": concept_gen, "passages": [{"chunkId": "chunk-gen", "text": text_two}]},
            DifficultyMaterials,
        )
        pub_payload = {
            "format": 1,
            "documents": [
                {
                    "id": doc_pub.id,
                    "filename": doc_pub.filename,
                    "sha256": doc_pub.sha256,
                    "pages": 1,
                    "graph": {
                        "concepts": [concept_pub],
                        "resources": {
                            concept_pub["id"]: {
                                "lesson": pack_pub.lesson.as_lesson(),
                                "tests": [q.model_dump() for q in pack_pub.tests],
                            }
                        },
                    },
                }
            ],
            "graph": {
                "concepts": [concept_pub],
                "prerequisites": [
                    {
                        "prerequisite": concept_pub["id"],
                        "dependent": "removed:old-concept",
                        "source": {"chunkId": "chunk-pub", "quote": text_one[:40]},
                    }
                ],
            },
            "chunks": {
                "chunk-pub": {
                    "id": "chunk-pub",
                    "document_id": doc_pub.id,
                    "course_id": course.id,
                    "page": 1,
                    "text": text_one,
                    "label": doc_pub.filename,
                }
            },
        }
        release = CourseRelease(
            course_id=course.id, version=3, sha256=fingerprint(pub_payload), payload=pub_payload
        )
        wb_run_id = str(uuid4())
        wb_run = Run(
            id=wb_run_id,
            course_id=course.id,
            owner_id="test-owner",
            input={"hierarchy_revision": 2, "hierarchy_ready": True},
            snapshot={"workflow": "course_preparation", "status": "completed"},
        )
        hierarchy = RunHierarchy(
            run_id=wb_run_id,
            ready=True,
            graph={
                "concepts": [concept_pub, concept_gen],
                "prerequisites": [],
                "topics": [],
                "related": [],
            },
            documents=[
                {
                    "id": doc_pub.id,
                    "filename": doc_pub.filename,
                    "sha256": doc_pub.sha256,
                    "pages": 1,
                    "graph": {
                        "concepts": [concept_pub],
                        "resources": {
                            concept_pub["id"]: {
                                "lesson": pack_pub.lesson.as_lesson(),
                                "tests": [q.model_dump() for q in pack_pub.tests],
                            }
                        },
                    },
                },
                {
                    "id": doc_gen.id,
                    "filename": doc_gen.filename,
                    "sha256": doc_gen.sha256,
                    "pages": 1,
                    "graph": {
                        "concepts": [concept_gen],
                        "resources": {
                            concept_gen["id"]: {
                                "lesson": pack_gen.lesson.as_lesson(),
                                "tests": [q.model_dump() for q in pack_gen.tests],
                            }
                        },
                    },
                },
            ],
        )
        db.add_all([release, wb_run, hierarchy])
        db.flush()
        course_id, release_id = course.id, release.id

    setup_res = client.post(
        "/api/evaluations/setups",
        json={
            "courseId": course_id,
            "documentId": "__all__",
            "releaseId": release_id,
            "workbenchRunId": wb_run_id,
            "overlayPublished": True,
        },
    )
    assert setup_res.status_code == 201, setup_res.text
    setup = setup_res.json()
    assert setup["materialSource"] == "workbench_generated"
    assert setup["material"]["documentCount"] == 2
    assert setup["release"]["version"] == 2
    assert setup["release"]["id"] == f"workbench:{wb_run_id}:2"
    assert "publishedReleaseId" not in setup["release"]

    too_few = client.post(
        "/api/evaluations/pseudo-runs",
        json={"setupId": setup["id"], "concepts": 1, "activities": 2},
    )
    assert too_few.status_code == 422 and "at least 2" in too_few.json()["detail"]

    started = client.post(
        "/api/evaluations/pseudo-runs",
        json={"setupId": setup["id"], "concepts": 2, "activities": 2},
    )
    assert started.status_code == 202, started.text
    view = started.json()
    assert view["materialSource"] == "workbench_generated"
    assert view["releaseVersion"] == 2
    assert view["workbenchRunId"] == wb_run_id
    assert len(launched) == 1

    frozen = thaw(tmp_path / "pseudo" / "test-owner" / view["id"] / "input.json")["payload"]
    merged = frozen["release"]
    assert len(merged["documents"]) == 2
    assert {c["id"] for c in merged["graph"]["concepts"]} == {
        concept_pub["id"],
        concept_gen["id"],
    }
    assert merged["graph"]["prerequisites"] == []
    assert set(merged["chunks"]) == {"chunk-pub", "chunk-gen"}


def test_pseudo_view_promotes_completed_with_failures_when_retries_succeed(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    setup = {
        "material": {"id": "m1"},
        "release": {"id": "r1", "version": 1},
        "learners": [{"id": "novice", "name": "Novice"}, {"id": "intermediate", "name": "Intermediate"}],
    }
    freeze(run_dir / "input.json", {"setup": setup})
    (run_dir / "job.json").write_text(
        '{"id":"' + ("a" * 32) + '","config":{"activities":2,"baselines":false}}',
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text('{"status":"completed_with_failures"}', encoding="utf-8")
    ep_ok = run_dir / "episodes" / digest(["novice", "adaptive"])[:16]
    ep_fail = run_dir / "episodes" / digest(["intermediate", "adaptive"])[:16]
    freeze(ep_ok / "result.json", {"status": "completed"})
    freeze(ep_fail / "result.json", {"status": "failed", "errorType": "RuntimeError"})

    assert evaluations._pseudo_view(run_dir)["status"] == "completed_with_failures"

    freeze(ep_fail / "retries" / "attempt-01" / "result.json", {"status": "completed"})
    assert evaluations._pseudo_view(run_dir)["status"] == "completed"
