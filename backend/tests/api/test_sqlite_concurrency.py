from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, select

from learnloop.persistence.database import Activity, Submission
from learnloop.runtime.worker import work_once
from tests.api.test_integration import prepare


def test_simultaneous_response_retries_create_one_submission_and_one_evidence_update(stack):
    client, factory, services, _ = stack
    course_id, _ = prepare(stack)
    session = client.post(
        f"/api/courses/{course_id}/sessions", json={"expectedLearnerVersion": 0}
    ).json()
    assert work_once(factory, services)
    activity = client.get(f"/api/sessions/{session['id']}").json()["activity"]
    with factory() as db:
        correct = db.get(Activity, activity["id"]).private["correctChoiceId"]
    barrier = Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        return client.post(
            f"/api/activities/{activity['id']}/responses",
            json={"operationId": "same-retry", "expectedLearnerVersion": 0, "choiceId": correct},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert [r.status_code for r in results] == [202, 202]
    assert results[0].json() == results[1].json()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Submission)) == 1
    assert work_once(factory, services)
    assert not work_once(factory, services)
    assert client.get(f"/api/courses/{course_id}/learner-state").json()["version"] == 1
