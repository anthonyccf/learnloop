# SQLite migration validation — 4 November 2026

The local API and worker now use SQLite/sqlite-vec at `backend/data/learnloop.db`,
Alembic revision `0004`. The original PostgreSQL database and Qdrant collection
were read only. A private ignored `.env.pre-sqlite-*` backup retains the original
configuration. The importer verified record fingerprints both during copying and
again immediately before activation.

Preserved records: 2 courses, 4 documents, 245 passages and vectors, 2 learner
states, 2 learning plans, 46 plan revisions, 174 runs/jobs, 2,198 events,
11 sessions, 83 activities, 57 submissions, 33 response details and 3 commands.

The source was revision `0002`: no course releases existed. New nullable session
pins are null. No release was invented. Current publication validation reports
missing/stale curriculum for one course and missing/stale lesson-scope review for
the other. Their uploaded files, generated graphs/materials and learning history
are preserved, but these courses need normal preparation/review before current
learner endpoints expose complete releases. No paid generation or re-embedding
was performed during migration.

Verification:

- 185 backend tests passed, including actual local cosine search, persistence,
  owner/course/document scoping, idempotent upserts, course publication,
  simultaneous duplicate response submissions and worker exclusion/recovery.
- Ruff passed for application code, migrations and changed scripts/tests.
  The full repository lint command also encounters pre-existing issues in
  unrelated scripts/tests; these were not broadened into the database migration.
- `pip check` passed; the teammate setup script completed successfully.
- Live API `/health/live`, authenticated `/health/ready`, and `/api/courses`
  returned HTTP 200 after restarting the API and worker.
- Readiness confirmed SQLite, sqlite-vec v0.1.9 and 1024-dimensional embeddings;
  generation configuration was present. Readiness does not make an inference call.
- Integrity and foreign-key checks passed on the migrated file. Existing vectors
  were reused; no Qdrant service is used by the active SQLite configuration.

SQLite executes background jobs sequentially and exact vector search scans the
scoped candidates. These are intentional local-prototype limits. Real-service
generation quality and learning effectiveness remain separate evaluations.


## Follow-up: restored imported course publication

The empty-map report was caused by absent current releases, not an unavailable
SQLite database or frontend connection. A SQLite backup was taken before repair.
Existing source-grounding receipts were valid for all 211 saved lesson packs.
Content-bound scope reviews were refreshed using the configured model. One
LLM-course scope was clarified from its existing cited source; two incomplete
LLM lessons were repaired through the normal Expert workflow and passed source
and scope validation. The other 209 lessons were retained.

Both courses now have validated release version 1. Requests through the live
frontend proxy returned HTTP 200 with 128 concepts/lessons for Large Language
Model and 83 concepts/lessons for Malware. Learner states, activities, submissions,
response details and sessions exactly matched the pre-repair backup afterwards.
The 13 release/legacy-repair regression checks passed; rejection still prevents
publication. These follow-up review/repair calls used the configured model and
are separate from the original no-generation database copy. Refreshing the
browser loads the restored map; restarting the services is unnecessary.
