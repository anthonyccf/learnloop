import copy

from sqlalchemy import select

from learnloop.persistence.database import Chunk, ChunkEmbedding, Course, Document, Run
from learnloop.runtime.events import new_run, run_status
from learnloop.runtime.worker import work_once
from tests.conftest import COURSE_TEXT
from tests.api.test_integration import prepare


def test_worker_saves_a_run_snapshot(stack):
    client, factory, services, _ = stack
    course_id = client.post('/api/courses', json={'title': 'Worker snapshot'}).json()['id']
    upload = client.post(f'/api/courses/{course_id}/documents',
                         files={'file': ('notes.txt', COURSE_TEXT.encode(), 'text/plain')}).json()
    assert work_once(factory, services)
    result = client.get(f"/api/documents/{upload['documentId']}/inspection",
                        params={'run_id': upload['runId'], 'kind': 'lessons'})
    assert result.status_code == 200
    assert result.json()['counts']['lessons'] > 0
    assert result.json()['runId'] == upload['runId']


def test_run_snapshots_are_isolated_and_private_to_their_material(stack):
    client, factory, _, _ = stack
    course_id = client.post('/api/courses', json={'title': 'Snapshot course'}).json()['id']
    with factory.begin() as db:
        course = db.get(Course, course_id)
        doc = Document(course_id=course_id, filename='notes.txt', sha256='a' * 64,
                       content_type='text/plain', content=b'original', status='prepared', pages=1,
                       graph={'concepts': [{'id': 'concept', 'title': 'Original', 'summary': 'first', 'sourceChunkIds': ['chunk']}],
                              'resources': {'concept': {'lesson': {'title': 'First lesson', 'explanation': 'Original explanation'}, 'tests': [{'prompt': 'First question', 'correctChoiceId': 'a'}]}}})
        other = Document(course_id=course_id, filename='other.txt', sha256='b' * 64,
                         content_type='text/plain', content=b'other', status='prepared', pages=1, graph={})
        db.add_all([doc, other])
        db.flush()
        doc_id, other_id = doc.id, other.id
        db.add(Chunk(id='chunk', document_id=doc_id, course_id=course_id, ordinal=0, page=1, text='original passage'))
        first = new_run(db, course, 'course_preparation', {'document_id': doc_id})
        first_id = first.id
        run_status(db, first_id, 'completed', 'First snapshot')

    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        graph = copy.deepcopy(doc.graph)
        graph['concepts'][0]['title'] = 'Revised'
        graph['resources']['concept']['lesson']['title'] = 'Second lesson'
        graph['resources']['concept']['lesson']['explanation'] = 'Revised explanation'
        graph['resources']['concept']['tests'][0]['correctChoiceId'] = 'b'
        graph['resources']['concept']['tests'][0]['prompt'] = 'Second question'
        doc.graph = graph
        db.get(Chunk, 'chunk').text = 'revised passage'
        second = new_run(db, db.get(Course, course_id), 'course_preparation', {'document_id': doc_id})
        second_id = second.id
        run_status(db, second_id, 'needs_review', 'Second snapshot')
        legacy = new_run(db, db.get(Course, course_id), 'course_preparation', {'document_id': doc_id})
        legacy_id = legacy.id
        legacy.snapshot = {**legacy.snapshot, 'status': 'completed'}
        active = new_run(db, db.get(Course, course_id), 'course_preparation', {'document_id': doc_id})
        active_id = active.id

    endpoint = f'/api/documents/{doc_id}/inspection'
    for kind, key, old, new in [('concepts', 'title', 'Original', 'Revised'),
                                ('lessons', 'title', 'First lesson', 'Second lesson'),
                                ('questions', 'prompt', 'First question', 'Second question'),
                                ('source_chunks', 'text', 'original passage', 'revised passage')]:
        first_view = client.get(endpoint, params={'run_id': first_id, 'kind': kind})
        second_view = client.get(endpoint, params={'run_id': second_id, 'kind': kind})
        assert first_view.status_code == second_view.status_code == 200
        assert first_view.json()['runId'] == first_id
        assert first_view.json()['items'][0][key] == old
        assert second_view.json()['items'][0][key] == new
    for kind, record_id, key, expected in [('lessons', 'lesson:concept', 'explanation', 'Original explanation'),
                                            ('questions', 'concept:question:1', 'correctChoiceId', 'a')]:
        preview = client.get(endpoint, params={'run_id': first_id, 'kind': kind, 'record_id': record_id})
        assert preview.status_code == 200
        assert preview.json()['relationship']['preview'][key] == expected
    relation = client.get(endpoint, params={'run_id': first_id, 'kind': 'concepts', 'record_id': 'concept'}).json()['relationship']
    assert relation['sourceChunks'][0]['text'] == 'original passage'
    assert client.get(endpoint, params={'run_id': legacy_id}).status_code == 409
    active_view = client.get(endpoint, params={'run_id': active_id, 'kind': 'source_chunks'})
    assert active_view.status_code == 200
    assert active_view.json()['inspectionMode'] == 'live'
    assert active_view.json()['items'][0]['text'] == 'revised passage'
    assert client.get(f'/api/documents/{other_id}/inspection', params={'run_id': active_id}).status_code == 409
    assert client.get(f'/api/documents/{other_id}/inspection', params={'run_id': first_id}).status_code == 409
    with factory.begin() as db:
        run = db.get(Run, first_id)
        run.input = {**run.input, 'document_id': other_id}
    runs = client.get(f'/api/courses/{course_id}/runs').json()
    assert next(run for run in runs if run['id'] == first_id)['documentId'] == doc_id


def test_restarted_run_inspection_shows_changes_and_freezes_them(stack):
    client, factory, _, _ = stack
    course_id, upload = prepare(stack)
    doc_id = upload['documentId']
    with factory.begin() as db:
        chunk = db.scalar(select(Chunk).where(Chunk.document_id == doc_id))
        db.add(ChunkEmbedding(chunk_id=chunk.id, owner_id='test-owner', course_id=course_id,
                              document_id=doc_id, model='test', dimensions=1, vector=b'\x00' * 4))
    response = client.post(f'/api/documents/{doc_id}/analyze', json={'force': True})
    assert response.status_code == 202
    run_id = response.json()['runId']
    endpoint = f'/api/documents/{doc_id}/inspection'
    initial = client.get(endpoint, params={'run_id': run_id, 'kind': 'concepts'}).json()
    assert initial['inspectionScope'] == 'changes'
    assert all(count == 0 for count in initial['counts'].values())
    assert initial['savedCounts']['source_chunks'] > 0
    assert initial['savedCounts']['embeddings'] > 0
    assert initial['savedCounts']['concepts'] > 0

    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        graph = copy.deepcopy(doc.graph)
        concept = graph['concepts'][0]
        concept['summary'] = 'Newly generated summary'
        pack = graph['resources'][concept['id']]
        pack['lesson']['title'] = 'Newly generated lesson'
        pack['tests'][0]['prompt'] = 'Newly generated question?'
        doc.graph = graph
        db.add(Chunk(id='new-run-chunk', document_id=doc_id, course_id=course_id,
                     ordinal=100, page=1, text='Newly generated passage'))
    for kind, field, expected in [
        ('concepts', 'summary', 'Newly generated summary'),
        ('lessons', 'title', 'Newly generated lesson'),
        ('questions', 'prompt', 'Newly generated question?'),
        ('source_chunks', 'text', 'Newly generated passage'),
    ]:
        view = client.get(endpoint, params={'run_id': run_id, 'kind': kind}).json()
        assert view['inspectionMode'] == 'live'
        assert view['total'] == 1 and view['items'][0][field] == expected
    with factory.begin() as db:
        run_status(db, run_id, 'completed', 'Snapshot complete')
        doc = db.get(Document, doc_id)
        graph = copy.deepcopy(doc.graph)
        graph['concepts'][0]['summary'] = 'A later change'
        doc.graph = graph
    snapshot = client.get(endpoint, params={'run_id': run_id, 'kind': 'concepts'}).json()
    assert snapshot['inspectionMode'] == 'snapshot'
    assert snapshot['items'][0]['summary'] == 'Newly generated summary'


def test_inspection_counts_only_current_concept_warnings(stack):
    client, factory, _, _ = stack
    _, upload = prepare(stack)
    doc_id = upload['documentId']
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        graph = copy.deepcopy(doc.graph)
        current_id = graph['concepts'][0]['id']
        graph['sourceIssues'] = {current_id: {'message': 'Needs review'}, 'retired': {'message': 'Old'}}
        doc.graph = graph
    view = client.get(f'/api/documents/{doc_id}/inspection').json()
    assert view['sourceWarningCount'] == 1


def test_evaluation_uses_frozen_snapshot_and_reports_missing_data(stack):
    client, factory, _, _ = stack
    course_id = client.post('/api/courses', json={'title': 'Evaluation'}).json()['id']
    with factory.begin() as db:
        doc = Document(course_id=course_id, filename='eval.txt', sha256='c' * 64,
                       content_type='text/plain', content=b'text', status='prepared', pages=1,
                       graph={'concepts': [{'id': 'a', 'sourceChunkIds': ['eval-chunk']}, {'id': 'b', 'sourceChunkIds': ['missing']}],
                              'coverage': {'processedPassages': 1, 'totalPassages': 2}})
        db.add(doc)
        db.flush()
        db.add(Chunk(id='eval-chunk', document_id=doc.id, course_id=course_id, ordinal=0, page=1, text='passage'))
        run = new_run(db, db.get(Course, course_id), 'course_preparation', {'document_id': doc.id})
        run_id = run.id
        run_status(db, run_id, 'completed', 'Done')
        doc.graph = {'concepts': []}
        active = new_run(db, db.get(Course, course_id), 'course_preparation', {'document_id': doc.id})
        active_id = active.id
    data = client.get(f'/api/agent-activity/runs/{run_id}/evaluation').json()
    assert data['snapshotAvailable'] is True
    assert (data['conceptsWithSourceLinks'], data['concepts']) == (1, 2)
    assert (data['processedPassages'], data['totalPassages']) == (1, 2)
    assert data['elapsedSeconds'] is not None
    assert data['reviewPassRate'] is None and data['cost'] is None
    active_data = client.get(f'/api/agent-activity/runs/{active_id}/evaluation').json()
    assert active_data['snapshotAvailable'] is False and active_data['concepts'] is None
    assert active_data['elapsedSeconds'] is None


def test_changed_lesson_links_to_unchanged_records(stack):
    client, factory, _, _ = stack
    _, upload = prepare(stack)
    doc_id = upload['documentId']
    run_id = client.post(f'/api/documents/{doc_id}/analyze', json={'force': True}).json()['runId']
    endpoint = f'/api/documents/{doc_id}/inspection'
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        graph = copy.deepcopy(doc.graph)
        concept_id = graph['concepts'][0]['id']
        graph['resources'][concept_id]['lesson']['title'] = 'Changed lesson only'
        doc.graph = graph
        chunk_id = db.scalar(select(Chunk.id).where(Chunk.document_id == doc_id))

    concepts = client.get(endpoint, params={'run_id': run_id, 'kind': 'concepts'}).json()
    assert any(item['id'] == concept_id for item in concepts['items'])
    for kind, record_id in [('concepts', concept_id), ('lessons', f'lesson:{concept_id}'),
                            ('source_chunks', chunk_id)]:
        response = client.get(endpoint, params={'run_id': run_id, 'kind': kind, 'record_id': record_id})
        assert response.status_code == 200
        assert response.json()['relationship']['selected']['id'] == record_id
    lesson = client.get(endpoint, params={'run_id': run_id, 'kind': 'lessons',
                                          'record_id': f'lesson:{concept_id}'}).json()
    assert lesson['relationship']['preview']['title'] == 'Changed lesson only'
    assert client.get(endpoint, params={'run_id': run_id, 'kind': 'concepts',
                                       'record_id': 'missing'}).status_code == 404
    with factory.begin() as db:
        run_status(db, run_id, 'completed', 'Snapshot complete')
    snapshot = client.get(endpoint, params={'run_id': run_id, 'kind': 'concepts', 'record_id': concept_id})
    assert snapshot.status_code == 200
    assert snapshot.json()['inspectionMode'] == 'snapshot'
