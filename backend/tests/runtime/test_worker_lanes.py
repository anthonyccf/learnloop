from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import Mock

from sqlalchemy import select

from learnloop.persistence.database import Course, Document, Job, Run, now
from learnloop.core.errors import ServiceError
from learnloop.runtime import worker
from learnloop.runtime.events import new_run, run_status


def test_expert_retries_retryable_failure_after_delay_and_stops_at_limit(stack, monkeypatch):
    _, factory, services, settings = stack
    with factory.begin() as db:
        course = Course(title="Retry", owner_id="test-owner")
        db.add(course)
        db.flush()
        document = Document(course_id=course.id, filename="notes.txt", sha256="a", content_type="text/plain", content=b"test")
        db.add(document)
        db.flush()
        run_id = new_run(db, course, "course_preparation", {"document_id": document.id}).id

    def fail(*args):
        raise ServiceError("connection_failed", "Connection failed")

    monkeypatch.setattr(worker, "execute", fail)
    for attempt in range(1, settings.worker_max_attempts + 1):
        assert worker.work_once(factory, services, "course_preparation")
        with factory() as db:
            job = db.scalar(select(Job).where(Job.run_id == run_id))
            run = db.get(Run, run_id)
            assert job.attempts == attempt
            if attempt < settings.worker_max_attempts:
                assert job.status == run.snapshot["status"] == "queued"
                assert timedelta(seconds=18) < job.lease_until - now() <= timedelta(seconds=20)
            else:
                assert job.status == run.snapshot["status"] == "failed"
                assert job.lease_until is None
        if attempt < settings.worker_max_attempts:
            assert not worker.work_once(factory, services, "course_preparation")
            with factory.begin() as db:
                db.scalar(select(Job).where(Job.run_id == run_id)).lease_until = now() - timedelta(seconds=1)


def test_default_command_starts_all_three_lanes(monkeypatch):
    monkeypatch.setattr("sys.argv", ["learnloop.worker"])
    monkeypatch.setattr(worker, "Services", Mock())
    monkeypatch.setattr(
        worker,
        "session_factory",
        Mock(return_value=Mock(kw={"bind": Mock(dialect=Mock(name="postgresql"))})),
    )
    lanes = []
    monkeypatch.setattr(
        worker, "work_loop", lambda factory, services, workflow, stop: lanes.append(workflow)
    )
    worker.main()
    assert sorted(lanes) == sorted(worker.WORKFLOWS)


def test_once_still_claims_only_one_job(monkeypatch):
    monkeypatch.setattr("sys.argv", ["learnloop.worker", "--once"])
    monkeypatch.setattr(worker, "Services", Mock())
    monkeypatch.setattr(
        worker,
        "session_factory",
        Mock(return_value=Mock(kw={"bind": Mock(dialect=Mock(name="postgresql"))})),
    )
    work = Mock()
    monkeypatch.setattr(worker, "work_once", work)
    worker.main()
    work.assert_called_once()
    assert work.call_args.args[2] is None


def test_sqlite_serializes_lanes_while_expert_is_busy(stack, monkeypatch):
    _, factory, services, _ = stack
    with factory.begin() as db:
        course = Course(title="Worker isolation", owner_id="test-owner")
        db.add(course)
        db.flush()
        runs = {workflow: new_run(db, course, workflow, {}).id for workflow in worker.WORKFLOWS}
    expert_started, release_expert = Event(), Event()
    executed = []

    def execute(factory, services, run_id):
        executed.append(run_id)
        if run_id == runs["course_preparation"]:
            expert_started.set()
            assert release_expert.wait(15)
        with factory.begin() as db:
            run_status(db, run_id, "completed", "Test task finished.")

    monkeypatch.setattr(worker, "execute", execute)
    with ThreadPoolExecutor(max_workers=3) as pool:
        expert = pool.submit(worker.work_once, factory, services, "course_preparation")
        try:
            assert expert_started.wait(5)
            # An expired lease still cannot cause duplicate execution while its owner holds the lock.
            with factory.begin() as db:
                job = db.scalar(select(Job).where(Job.run_id == runs["course_preparation"]))
                job.lease_until = now() - timedelta(seconds=1)
            assert not worker.work_once(factory, services, "course_preparation")
            assert not worker.work_once(factory, services, "next_activity")
            assert not worker.work_once(factory, services, "assessment")
            assert not expert.done()
            with factory() as db:
                jobs = {job.run_id: job for job in db.scalars(select(Job))}
                assert jobs[runs["next_activity"]].status == "queued"
                assert jobs[runs["assessment"]].status == "queued"
                assert jobs[runs["course_preparation"]].attempts == 1
        finally:
            release_expert.set()
        assert expert.result(timeout=5)
    assert worker.work_once(factory, services, "next_activity")
    assert worker.work_once(factory, services, "assessment")
    assert sorted(executed) == sorted(runs.values())
