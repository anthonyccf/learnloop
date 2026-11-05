"""Explicit local-owner reset, preserving uploads, passages and historical responses.

Run with --apply to back up graphs and queue one whole-course rebuild per course.
"""
import argparse
import json
from datetime import datetime, UTC
from pathlib import Path
from sqlalchemy import select
from learnloop.core.config import get_settings
from learnloop.persistence.database import Course, Document, StudySession, LearningPlan, Job, Run, session_factory
from learnloop.runtime.events import new_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    settings = get_settings()
    if not settings.generation_ready or 'openrouter.ai' not in settings.llm_base_url:
        raise SystemExit('A configured OpenRouter provider is required.')
    factory = session_factory(settings)
    with factory.begin() as db:
        courses = list(db.scalars(select(Course).where(Course.owner_id == settings.local_owner_id).with_for_update()))
        ids = [c.id for c in courses]
        docs = list(db.scalars(select(Document).where(Document.course_id.in_(ids))))
        active_jobs = list(db.scalars(select(Job).join(Run).where(Run.course_id.in_(ids), Job.status.in_(['running','queued']))))
        if active_jobs:
            raise SystemExit('Finish or stop active jobs before rebuilding.')
        print(json.dumps({'courses': [c.title for c in courses], 'documents': len(docs), 'apply': args.apply}))
        if not args.apply:
            return
        backup = Path(__file__).resolve().parents[3] / 'tmp' / ('pyramid-backup-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '.json')
        sessions = list(db.scalars(select(StudySession).where(StudySession.course_id.in_(ids))))
        plans = list(db.scalars(select(LearningPlan).where(LearningPlan.course_id.in_(ids))))
        backup.write_text(json.dumps({'documents': [{'id': d.id, 'status': d.status, 'graph': d.graph} for d in docs],
            'sessions': [{'id': s.id, 'status': s.status} for s in sessions],
            'plans': [{'id': p.id, 'data': p.data} for p in plans]}, ensure_ascii=False), encoding='utf-8')
        for d in docs:
            d.graph = {}
            d.status = 'indexed'  # Existing immutable passages/vectors remain valid.
        for session in sessions:
            session.status = 'ended'
        for plan in plans:
            plan.data = {}  # No old planned activity may reference the replaced catalog.
        for course in courses:
            document_ids = [d.id for d in docs if d.course_id == course.id]
            if document_ids:
                run = new_run(db, course, 'course_preparation', {'document_id': document_ids[0], 'document_ids': document_ids, 'rebuild_course': True})
                print('queued',course.title,run.id)
        print('backup',backup)

if __name__ == '__main__':
    main()
