import copy

from learnloop.agents.expert import agent
from learnloop.core.errors import ServiceError
from learnloop.persistence.database import Document, Run
from tests.api.test_integration import prepare


def test_single_document_run_does_not_generate_other_materials(stack, monkeypatch):
    client, factory, services, _ = stack
    course_id, first = prepare(stack)
    second = client.post(f'/api/courses/{course_id}/documents',
                         files={'file': ('other.txt', b'Other course content about statistics.', 'text/plain')}).json()
    with factory.begin() as db:
        sibling = db.get(Document, second['documentId'])
        sibling.status = 'prepared'
        sibling.graph = {'concepts': [], 'resources': {'retained': {'lesson': {'title': 'Keep'}}}}
        sibling_before = copy.deepcopy(sibling.graph)
    selected = first['documentId']
    receipt = client.post(f'/api/documents/{selected}/analyze', json={'force': True}).json()

    for name in ('prepare_graph', 'deduplicate_course', 'organize_course', 'prepare_curriculum'):
        monkeypatch.setattr(agent, name, lambda *args: None)
    seen = []
    monkeypatch.setattr(agent, 'prepare_materials', lambda factory, services, run_id, document_id, *args: seen.append(document_id) or [])
    monkeypatch.setattr(agent, 'publish_course', lambda *args: (_ for _ in ()).throw(ServiceError('course_not_ready', 'Lesson scope review is missing or stale.', False)))
    agent.run(factory, services, receipt['runId'])

    assert seen == [selected]
    with factory() as db:
        assert db.get(Document, second['documentId']).graph == sibling_before
        run = db.get(Run, receipt['runId'])
        assert run.snapshot['status'] == 'needs_review'
        assert 'selected material was prepared' in run.snapshot['summary']
        assert 'could not be published' in run.snapshot['summary']
