# Complete course releases

Implemented for proposal gap 9 on 4 November 2026. Concept discovery writes a `prepared` catalog. Learner endpoints expose only a complete, validated `ll_course_releases` snapshot. The first release appears after all uploaded documents have finished analysis, organization, curriculum and resource preparation. A later preparation failure leaves the previous release available.

## Publication contract

`publish_course` locks the course, documents and source rows, validates coverage and source receipts, then inserts one immutable graph-plus-resources snapshot in the same transaction that marks documents published. It checks current organization/curriculum, cycles and references, scoped lesson review, valid lessons/private rubrics and at least two distinct questions at every assessment difficulty. The present curriculum has one primary lesson per objective at its assigned layer, plus Basic/Intermediate/Advanced quiz banks.

The snapshot retains document hashes, source text/page metadata, catalog and organization, curriculum, lessons, private questions, grounding/scope receipts and a SHA-256 digest. Identical latest content reuses the existing release, including concurrent worker retries. A changed complete snapshot receives a new monotonically increasing version. Failed transactions expose neither a new version nor partial resources. ORM updates/deletes are rejected; integrity mismatches fail closed on reads. This protects application writes and detects accidental/manual corruption; it is not protection against a privileged database administrator rewriting both content and hashes.

New sessions bind to a release before scheduling work. Existing sessions retain their release through new publications; ending a session and starting another adopts the newest version. A newly published topic outside an existing session's release requires a new session. Legacy unpinned sessions acquire a pin on their next learning action. Tutor planning, retrieval, bank selection, chat and assessment all resolve that snapshot. Fallback production questions remain possible after a bank is exhausted, with source review against the pinned passages. Experiments continue using their fixed pools.

Legacy learner-configurable targets are stored separately in plan revisions. Curriculum-assigned targets continue following their layer. Learner evidence and historical submissions are preserved across releases; no progress reset is performed.

## APIs

- `GET /api/courses/{id}` includes current release ID/version/hash and the released public graph. Document preparation status and counts describe the working preparation records.
- `GET /api/courses/{id}/releases` returns owner-scoped version metadata, without private banks or snapshot payloads.
- `POST /api/courses/{id}/releases` validates already-prepared records and publishes atomically; an identical retry returns the same release. Invalid/incomplete preparation returns 409. This endpoint performs no generation.
- `GET /api/courses/{id}/materials?releaseId=UUID` returns public lessons from a selected release in the owned course. Omit the parameter for the latest complete release.
- Session responses include `releaseId`. Activities retain the pin privately; keys, hints and rubrics are still excluded from public activity projections.

Evaluation `export-unit --release UUID` uses the specified release and writes `release-provenance.json`, binding the release ID/version/hash to the exported unit. Run manifests retain that provenance; changed provenance invalidates resume. Existing manually curated bundles are not retroactively assigned a release.

## Rollout for existing installations

The production migration and service restart were **not performed** by this implementation task. Validation uses isolated PostgreSQL schemas and fake model/vector services.

1. Use a maintenance window, preserve a database backup, and stop the API/worker before schema changes. Do not run the old worker concurrently with the updated preparation workflow.
2. From `backend`, run `.venv\Scripts\python.exe -m alembic upgrade head`. Revision `0003` adds the release table and nullable session pin. It does not delete content, evidence, responses or sessions, and does not invent releases for unvalidated records.
3. Start the updated API/worker. A legacy course without a complete release returns an empty learner graph/material list until first-release validation finishes. Existing saved responses remain stored.
4. For each course, request materials for one prepared/published anchor document through `POST /api/documents/{documentId}/materials`. The resumed Expert workflow checks the whole course, retains valid checkpoints and re-reviews existing current-version lessons whose scope fingerprint is absent. Older/incomplete resources may require regeneration. These source/scope reviews use the configured model and can incur provider charges. A saved interrupted preparation should be resumed/retried through its existing activity controls.
5. Confirm the run completed and the course has release version 1. Do not bypass a source/curriculum/scope failure. If all current receipts already exist, the explicit publication endpoint can validate/promote without model calls.
6. Resume learning. A new upload prepares privately; the existing complete version remains available until the next version commits.

No existing course reset or automatic research approval is part of this rollout.

## Verification

On 4 November 2026, the complete backend suite passed: **183 tests**, with integration checks enabled. Ruff lint and formatting passed. Alembic discovers `0003` as the migration head. All database tests use isolated schemas; no paid model calls, production migration or service restart was performed.

Regression tests cover initial staging, missing packs, stale sources and curriculum, invalid lesson scope receipts, incomplete quiz levels, failed preparations, idempotent/concurrent publication, transaction rollback, session/source pinning through a newer release, independent assessment, ownership/private-key projection, immutable ORM rows, integrity failures and evaluation export provenance. Migration checks apply `0002` and `0003` to an isolated old schema and preserve the existing course/session records and null legacy pin.
