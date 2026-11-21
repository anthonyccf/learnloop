from learnloop.runtime.worker import work_once
from tests.conftest import COURSE_TEXT


def test_expert_usage_persists_and_reports_partial_cost(stack):
    client, factory, services, _ = stack
    course_id = client.post('/api/courses', json={'title': 'Expert cost'}).json()['id']
    upload = client.post(f'/api/courses/{course_id}/documents',
                         files={'file': ('notes.txt', COURSE_TEXT.encode(), 'text/plain')}).json()
    original = services.generate
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        services.last_generation_usage = {'inputTokens': 10, 'outputTokens': 5, 'costUsd': 0.002}
        return original(*args, **kwargs)

    services.generate = generate
    assert work_once(factory, services)
    run = next(r for r in client.get(f'/api/courses/{course_id}/runs').json() if r['id'] == upload['runId'])
    assert 0 < run['expertUsage']['reportedCalls'] <= len(calls)
    assert abs(run['expertUsage']['reportedCostUsd'] - run['expertUsage']['reportedCalls'] * 0.002) < 1e-9
    assert run['expertUsage']['unreportedCalls'] == 0


def test_old_run_cost_is_unknown(stack):
    client, factory, _, _ = stack
    course_id = client.post('/api/courses', json={'title': 'Legacy cost'}).json()['id']
    upload = client.post(f'/api/courses/{course_id}/documents',
                         files={'file': ('notes.txt', COURSE_TEXT.encode(), 'text/plain')}).json()
    run = next(r for r in client.get(f'/api/courses/{course_id}/runs').json() if r['id'] == upload['runId'])
    assert run['expertUsage'] is None


def test_live_total_reports_missing_provider_cost(stack):
    from learnloop.persistence.database import ExpertUsageCall, Run

    client, factory, _, _ = stack
    course_id = client.post('/api/courses', json={'title': 'Partial cost'}).json()['id']
    upload = client.post(f'/api/courses/{course_id}/documents',
                         files={'file': ('notes.txt', COURSE_TEXT.encode(), 'text/plain')}).json()
    with factory.begin() as db:
        run = db.get(Run, upload['runId'])
        run.input = {**run.input, '_expert_usage_enabled': True}
        db.add_all([ExpertUsageCall(run_id=run.id, data={'costUsd': 0.012}),
                    ExpertUsageCall(run_id=run.id, data={'costUsd': None})])
    run = next(r for r in client.get(f'/api/courses/{course_id}/runs').json() if r['id'] == upload['runId'])
    assert run['expertUsage'] == {'reportedCostUsd': 0.012, 'reportedCalls': 1,
                                  'unreportedCalls': 1, 'priorUsageUnknown': False}
