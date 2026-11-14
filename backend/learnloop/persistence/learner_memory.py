"""Scoped learner memory derived from assessments and private activity notes."""

import hashlib

from sqlalchemy import or_, select

from learnloop.core.domain import DIFFICULTIES, effective_state, target_difficulty
from learnloop.persistence.database import Activity, StudySession, now


def record_tutor_observation(activity, message, observation):
    # The current learner turn, not client-provided chat history, supplies evidence.
    quote = observation.quote.strip() if observation else ""
    if not quote or quote not in message:
        return
    notes = activity.private.get("tutorObservations", [])
    digest = hashlib.sha256(message.strip().encode()).hexdigest()
    if any(note["id"] == digest for note in notes):
        return
    activity.private = {
        **activity.private,
        "tutorObservations": [
            *notes[-7:],
            {
                "id": digest,
                "kind": observation.kind,
                "summary": observation.summary,
                "at": now().isoformat(),
            },
        ],
    }


def learner_memory(db, state, release_id, concepts):
    if not concepts:
        return {}
    notes, checked = {}, {}
    rows = db.execute(
        select(
            Activity.concept_id,
            Activity.difficulty,
            Activity.id,
            Activity.private["tutorObservations"],
            Activity.private["memoryTarget"],
        )
        .join(StudySession, StudySession.id == Activity.session_id)
        .where(
            StudySession.course_id == state.course_id,
            StudySession.owner_id == state.owner_id,
            StudySession.release_id == release_id,
            Activity.concept_id.in_([concept["id"] for concept in concepts]),
            or_(
                Activity.private["tutorObservations"].as_string().is_not(None),
                Activity.private["memoryTarget"].as_string().is_not(None),
            ),
        )
    )
    for concept_id, difficulty, activity_id, observations, target in rows:
        record = state.evidence.get(concept_id, {}).get(difficulty, {})
        if target and activity_id in record.get("independentHistoryActivityIds", []):
            key = (target.get("assessmentId"), target.get("activityId"), target.get("id"))
            checked[key] = max(checked.get(key, -1), DIFFICULTIES.index(difficulty))
        for note in observations or []:
            key = (concept_id, difficulty, note["kind"])
            if key not in notes or note["at"] > notes[key]["at"]:
                notes[key] = {**note, "activityId": activity_id, "difficulty": difficulty}

    memory = {}
    for concept in concepts:
        id = concept["id"]
        records = state.evidence.get(id, {})
        strengths, gaps, observations = [], [], []
        for difficulty in DIFFICULTIES:
            record = records.get(difficulty, {})
            assessment_ids = record.get("assessmentIds", [])
            status = effective_state(record)
            if status in {"demonstrated", "review_due"}:
                strengths.append(
                    {
                        "difficulty": difficulty,
                        "status": status,
                        "reviewAt": record.get("reviewAt"),
                        "assessmentIds": assessment_ids[-2:],
                    }
                )
            assessed_at = record.get("lastAssessedAt", "")
            level = DIFFICULTIES.index(difficulty)
            if assessment_ids:
                latest_id = assessment_ids[-1]
                misconception = next(
                    (
                        item
                        for item in reversed(record.get("misconceptions", []))
                        if item.get("assessmentId") == latest_id
                    ),
                    None,
                )
                if misconception and checked.get((latest_id, None, None), -1) < level:
                    gaps.append(
                        {
                            "summary": misconception["description"],
                            "assessmentId": latest_id,
                            "difficulty": difficulty,
                            "at": assessed_at,
                            "status": "suspected",
                        }
                    )
            strength = notes.get((id, difficulty, "strength"))
            if strength:
                observations.append(strength)
            gap = notes.get((id, difficulty, "gap"))
            if gap and checked.get((None, gap["activityId"], gap["id"]), -1) < level:
                gaps.append({**gap, "status": "suspected"})
        memory[id] = {
            "targetDifficulty": target_difficulty(concept),
            "status": effective_state(records.get(target_difficulty(concept))),
            "strengths": strengths,
            "gap": max(
                gaps, key=lambda gap: (bool(gap.get("assessmentId")), gap["at"]), default=None
            ),
            "observation": max(observations, key=lambda note: note["at"], default=None),
        }
    return memory
