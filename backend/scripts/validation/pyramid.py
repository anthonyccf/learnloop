"""Read-only audit of the local owner's regenerated learning pyramids."""
import json
from collections import Counter
from pathlib import Path
from sqlalchemy import select
from learnloop.agents.expert.curriculum import validate_curriculum
from learnloop.agents.expert.materials import MATERIALS_VERSION, material_valid, difficulty_complete
from learnloop.core.config import get_settings
from learnloop.persistence.database import session_factory, Course, Document, Chunk, Run
from learnloop.persistence.repository import course_graph


def main():
    settings = get_settings()
    report = []
    with session_factory(settings)() as db:
        for course in db.scalars(select(Course).where(Course.owner_id == settings.local_owner_id)):
            docs = list(db.scalars(select(Document).where(Document.course_id == course.id)))
            graph = course_graph(db, course.id)
            assignments = {id: i for d in docs for id, i in d.graph.get('curriculum', {}).get('objectives', {}).items()}
            counts = Counter(i['layer'] for i in assignments.values())
            issues = []
            if assignments:
                try:
                    validate_curriculum({'objectives': list(assignments.values())}, graph['concepts'], graph['prerequisites'])
                except Exception as error:
                    issues.append(type(error).__name__ + ': ' + getattr(error, 'message', 'Invalid curriculum'))
            lessons = []
            for d in docs:
                chunks = {c.id: {'text': c.text} for c in db.scalars(select(Chunk).where(Chunk.document_id == d.id))}
                for id, pack in d.graph.get('resources', {}).items():
                    if pack.get('version') != MATERIALS_VERSION or not material_valid(pack, chunks) or not difficulty_complete(pack):
                        issues.append('Invalid material: ' + id)
                    if pack.get('lessonsByDifficulty'):
                        issues.append('Unexpected repeated level variants: ' + id)
                    lessons.append(pack['lesson'])
                if d.graph.get('sourceIssues'):
                    issues.append({'document': d.id, 'sourceIssues': d.graph['sourceIssues']})
            bodies = [' '.join(l['explanation'].casefold().split()) for l in lessons]
            if len(set(bodies)) != len(bodies):
                issues.append('Duplicate primary lesson explanations')
            runs = [r for r in db.scalars(select(Run).where(Run.course_id == course.id)) if r.input.get('rebuild_course')]
            status = max(runs, key=lambda r: r.input.get('_started_at', '')).snapshot['status'] if runs else 'unknown'
            report.append({'course': course.title, 'status': status, 'concepts': len(graph['concepts']),
                'layerCounts': dict(counts), 'lessons': len(lessons), 'documents': [{'name': d.filename, 'status': d.status, 'sections': len(d.graph.get('analysis', {}).get('sections', {}))} for d in docs],
                'mergedGoals': sum(len(d.graph.get('conceptAliases', {})) for d in docs), 'issues': issues})
    output = Path(__file__).resolve().parents[3] / 'tmp' / 'pyramid-validation.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
