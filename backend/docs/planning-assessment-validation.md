# Tutor planning and rubric assessment

Implemented for proposal gaps 3 and 4 on 23 October 2026. This extends the existing difficulty and source-support checks.

## Learning goals and plans

The Tutor page has a **Your learning goal** editor. Saving it creates a versioned course/owner plan revision. Explicit session focus takes precedence over goal scope. A changed goal affects the next prepared activity and retains pending answers.

Candidate actions are introduction, practice, remediation, difficulty adjustment, prerequisite revisiting, target reassessment and related-concept advancement. Candidates must satisfy each prerequisite at its own target difficulty. A goal on a blocked concept includes eligible unmet ancestors. Ranking uses `3*need + uncertainty + 4*urgency + 2*recentPerformance + 2*goalMatch`, plus a 0.5 related-advancement preference after demonstration. The model chooses among the first twelve candidates and provides a short rationale. The runtime rejects invented candidates and stale graph, learner or plan snapshots. The selected objective/action/difficulty and rationale are saved on the activity; all ranked candidates and scores are retained in the plan revision.

`GET /api/courses/{id}/plan` returns the current plan and evidence staleness. `POST /api/courses/{id}/plan/revise` takes `operationId`, `expectedPlanVersion`, `expectedLearnerVersion`, a `goal` (`description`, `conceptIds`), optional course-scoped `activityIds`, and optional `reviewDates` (`conceptId`, timezone-aware `reviewAt`). Duplicate operations reuse their original snapshot. Conflicting payloads, stale versions, invalid references and unmet prerequisites fail before writes. Ordinary Next remains learner controlled.

## Rubrics and diagnostics

New Expert tests include private reference answers and weighted, source-cited criteria with bounded choice scores. Only the keyed answer may meet every criterion. All rubric facts and mappings are included in source review. Legacy tests receive a reviewed rubric when assigned or assessed; original course packs and learner evidence remain intact.

Learners can add an optional explanation to an MCQ answer. The assessor receives source passages, the reference answer/rubric, actual difficulty, persisted hints, prior level-specific evidence, recent assessment records and server response timing. Every criterion must appear exactly once in coverage. For choice-only responses the authored rubric determines coverage; written reasoning can reduce that coverage. Positive reasoning credit requires an exact learner-response quote. Misconceptions must cite a real response quote and a valid criterion. Full criterion credit cannot coexist with a misconception on that criterion. Invalid output stops without learner-state mutation.

Correctness remains server-keyed. Independent demonstration additionally requires full rubric coverage, no hint and no unresolved uncertainty. Partial answers do not qualify. Assessment records retain coverage/score, reasoning, misconception quotes, prior assessment references, contradiction signals and timing. Aggregates append assessment references and diagnostic history at the actual difficulty. Conflicts with demonstrated/review-due evidence trigger reassessment; two later independent qualifying responses resolve contradiction records without removing their history. Gap 5 now defines confirmed weakness as two consecutive distinct, unassisted and certain rubric failures at a previously demonstrated level; see `confirmed-weakness-validation.md`.

`POST /api/activities/{id}/present` records the first server presentation time idempotently. Submission records elapsed presentation-to-submission time, or assignment-to-submission if presentation was unavailable. The basis is explicit; unknown historical timestamps remain null. Timing can include reading, pauses and network delay, so it is context and never independently proves correctness, weakness or mastery. Historical assessments remain readable without invented rubric/timing results.

## Persistence and verification

Migration `0002` adds `ll_learning_plans`, `ll_plan_revisions` and `ll_response_details`. It does not alter or delete existing course, activity, submission or evidence columns. Apply with `python -m alembic upgrade head` before starting the updated API/worker.

- 111 backend tests passed, including the original regressions and an isolated initial-schema-to-0002 migration test preserving existing course data.
- 43 frontend tests and TypeScript checks passed. UI tests cover diagnostic visibility and escaped response quotes.
- The real-service check **passed at all three difficulties**, with six activity/assessment cycles (three with written reasoning), saved goals, model-selected actions, full criterion coverage and server timing. Existing course/evidence hashes were unchanged and all temporary SQL/vector data was removed. The command is `python -m scripts.validation.planning_assessment`. It uses its own disposable PostgreSQL schema and vector owner. The report is `../../tmp/planning-assessment-validation/report.json`.
- Live-test answers deliberately use the private test oracle, including reference answers for written-reasoning checks. This validates orchestration, source review and evidence partitioning, not learning gains or independent grading quality.

General standalone essay activities, optimized planning weights, independent rubric/diagnostic quality measurement, controlled simulator experiments and cost budgets remain outside these two changes.

The local database is upgraded to revision `0002`; the API and worker have been restarted. The frontend proxy explicitly permits the new plan/presentation endpoints and namespaced concept-target IDs, retaining route and origin restrictions.
