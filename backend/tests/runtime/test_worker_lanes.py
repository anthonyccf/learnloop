from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import Mock

from sqlalchemy import select

from learnloop.persistence.database import Course, Job, now
from learnloop.runtime import worker
from learnloop.runtime.events import new_run, run_status


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
