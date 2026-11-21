from sqlalchemy import select

from learnloop.persistence.database import Course, Job, Run
from learnloop.runtime.cancellation import check_stopped
from learnloop.runtime.events import new_run, step
from learnloop.runtime.worker import work_once


def make_run(client, factory):
    course_id = client.post('/api/courses', json={'title': 'Stop test'}).json()['id']
    with factory.begin() as db:
        run = new_run(db, db.get(Course, course_id), 'course_preparation', {})
        return run.id


def test_stop_queued_run_does_not_start_worker(stack):
    client, factory, services, _ = stack
    run_id = make_run(client, factory)
    response = client.post(f'/api/agent-activity/runs/{run_id}/stop')
    assert response.json()['status'] == 'stopped'
    assert client.get(f'/api/agent-activity/runs/{run_id}').json()['status'] == 'stopped'
    assert not work_once(factory, services)
    with factory() as db:
        assert db.scalar(select(Job).where(Job.run_id == run_id)).status == 'done'
    assert client.post(f'/api/agent-activity/runs/{run_id}/stop').status_code == 409


def test_running_stop_is_acknowledged_at_checkpoint(stack, monkeypatch):
    client, factory, services, _ = stack
    run_id = make_run(client, factory)

    def execute(factory, services, executing_id):
        response = client.post(f'/api/agent-activity/runs/{executing_id}/stop')
        assert response.json()['status'] == 'stopping'
        assert client.get(f'/api/agent-activity/runs/{executing_id}').json()['status'] == 'running'
        check_stopped(factory, executing_id)
        raise AssertionError('Worker continued after stop')

    monkeypatch.setattr('learnloop.runtime.worker.execute', execute)
    assert work_once(factory, services)
    assert client.get(f'/api/agent-activity/runs/{run_id}').json()['status'] == 'stopped'
    with factory() as db:
        assert db.scalar(select(Job).where(Job.run_id == run_id)).status == 'done'


def test_stop_rolls_back_work_at_event_checkpoint(stack):
    import pytest
    from learnloop.runtime.cancellation import RunStopped

    client, factory, _, _ = stack
    run_id = make_run(client, factory)
    client.post(f'/api/agent-activity/runs/{run_id}/stop')
    with pytest.raises(RunStopped), factory.begin() as db:
        run = db.get(Run, run_id)
        run.input = {**run.input, 'partial': True}
        step(db, run_id, 'expert', 'Saving', 'Saving work')
    with factory() as db:
        assert 'partial' not in db.get(Run, run_id).input
