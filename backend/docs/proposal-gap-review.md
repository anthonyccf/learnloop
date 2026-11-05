# Agent implementation versus proposal

Reviewed 21 October 2026. Scope: the Python agents, shared domain rules, persistence, runtime, API contracts, and existing validation scripts/tests. The initial review changed no application code. Gap #1 was subsequently addressed in code as described below.

Requirements were checked against the supplied `[Group 72] LearnLoop Project Proposal_NeurIPS.pdf`, especially Sections 4-5 and Appendices B-C, and the corresponding r8 LaTeX source. This review does not assume that the separately named final Word document is identical. The existing architecture guide correctly acknowledges several major omissions; the findings below also check executable behavior.

## Assessment

The core construct-teach-assess loop exists. Gaps #1â€“5 now have implementations covering source review, three-level resources, bounded Tutor planning and rubric-based diagnostics. Full proposal coverage remains incomplete, including controlled evaluation, usage budgets and complete resource releases. Passing regression tests establishes that the current implementation behaves as tested; it does not establish proposal compliance or learning effectiveness.

## Implemented foundations

- Separate Expert, Tutoring, and Assessing entry points and prompts, dispatched through durable jobs.
- Page-aware overlapping extraction, bge-m3 embedding/Qdrant integration, and SQL-checked course-scoped retrieval.
- Exhaustive section discovery, concept merging, topic organization, prerequisite/related relationships, and structural/DAG validation.
- Lessons, worked examples, flashcards, hints, private answer keys, and two multiple-choice questions per difficulty per newly prepared concept; fallback question generation and reviewed legacy upgrades.
- Persistent learner evidence, prerequisite gating, review priority, hint tracking, two distinct independent correct activities before demonstration, and seven-day review dates.
- Saved assessments, atomic evidence/event commits, version checks, duplicate-submission protection, pending-activity resumption, and checkpointed preparation.
- Grounded lesson chat and public activity traces. Tutor chat while a question is pending marks the activity as assisted.

## Prioritized gaps

### 1. Enforce source support before use â€” implemented, semantic quality still needs evaluation

**Proposal:** Sections 4.3, A.2, B.2 and C.1 require unsupported resources to be rejected or flagged before use.

**Previous gap:** Structural graph validation did not resolve citations. Unknown passage IDs were silently omitted from public references, leaving questions assignable without valid source links. Expert materials had no separate source-support gate.

**Implemented:**

- `core/grounding.py` checks all nested source IDs against supplied passages, rejects empty/unknown evidence and fingerprints the reviewed content plus cited passage text.
- `agents/grounding.py` makes a separate structured source-review call. Faithful paraphrases are allowed; known passage IDs alone are insufficient. The review checks claims, examples and private question keys, returning supported, unsupported or uncertain. Unsupported and uncertain items stop with a durable `needs_review` outcome.
- Expert section discovery reviews generated concepts/prerequisites before checkpoint/publication. Completed section reviews are reused only when their fingerprints match. Material packs, including retained private tests during lesson upgrades, are reviewed before saving. Failed material reviews appear as safe `sourceIssues` in document review, without exposing test keys.
- Tutor validates both prepared and fallback questions plus the selected concept before assignment. Source resolution uses authorized published SQL records. The assignment rechecks source fingerprints before commit.
- Assessment checks question support before changing learner evidence. Older questions resolve their saved page anchors and receive review; missing/unavailable sources block assessment. Existing receipts are reused only for unchanged questions/passages, and sources are checked again before the assessment commit. Feedback now receives the source passages.
- Public lessons, lesson counts and Tutor chat require a current material receipt. Older packs remain stored but are withheld until reviewed through `POST /api/documents/{id}/materials`; valid existing lessons/tests are retained during that review. No database migration is required.

**Limits:** Source-ID/ownership checks are deterministic. Semantic support remains a model judgment, using a separate call to the configured model, and can still be wrong. Regression tests use controlled review outcomes; a real-service grounding-quality evaluation remains necessary. This change does not retroactively rewrite every historical graph or assessment. Saved concepts/questions receive source review when used for new practice, and old material packs must be revalidated before teaching use.

**Validation:** Regression coverage includes unknown/empty/nested citations, supported paraphrases, unsupported/uncertain reviews, private-data projection, saved/fallback question rejection, invalidated receipts, legacy activity review, changed/unpublished sources, source changes during model calls, and material revalidation without resetting tests or learner progress.

### 2. Difficulty-aware resources and adaptation â€” implemented

**Proposal:** Sections 4.1-4.2 require Basic, Intermediate and Advanced resources, difficulty-specific evidence, and overall/prerequisite states relative to each concept's target.

**Previous gap:** Generated questions and eligibility checks were fixed to Intermediate, despite evidence being stored by difficulty.

**Implemented:**

- Typed Basic/Intermediate/Advanced question difficulties and concept targets. New packs contain two distinct questions per level, with private hints/answer explanations, and three teaching posts with their own objectives, examples and source references.
- Expert source review covers the complete pack, including the level-specific lessons. Legacy packs can add Basic/Advanced lessons and missing questions while retaining their existing Intermediate lesson and original questions. Old unlabelled questions remain Intermediate; existing grounding receipts remain valid for unchanged legacy content.
- Tutor filters the bank by selected difficulty and requests the same level in fallback generation. Mislabeled fallback output is rejected rather than relabeled.
- Deterministic adaptation starts at the concept target (Intermediate by default), steps down after wrong/uncertain/hint-assisted responses, and steps up after demonstrated independent evidence at the lower level. Review-due target evidence is reassessed at the target. The activity records its actual difficulty, and assessment updates only that level.
- Overall state is derived from the target-level evidence. Each prerequisite must be demonstrated at its own target. Basic success does not establish an Intermediate/Advanced target, and higher-level attempts do not silently rewrite lower-level evidence.
- An owner-scoped, version-checked target endpoint and a Learning target selector configure individual concepts. Changes retain evidence, preserve reviewed relationships and invalidate stale planning versions. Pending activities keep their original difficulty.
- The lesson view provides a level selector and a Prepare all lesson levels action for older material. Tutor chat uses the teaching variant matching the assigned activity. Progress/readiness displays use target-aware overall states while retaining per-level evidence views.

**Verification:** 91 backend tests pass, including separate-level evidence, prerequisite gating, step-down/recovery, target changes, wrong-level rejection and non-destructive legacy upgrades. A real-service test generated all three lesson levels and six questions, assigned/assessed two independent questions at each level, and reached demonstrated evidence separately at all three levels. The test used an isolated schema, removed its temporary SQL/vector data and confirmed unchanged existing course/learner data. See `difficulty-adaptation-validation.md` and `../../tmp/difficulty-validation/report.json`.

**Remaining boundaries:** The adaptation is explicit policy, not the utility-based action planning in gap #3. Rich rubrics/free-form assessment remain gap #4; controlled measures of difficulty suitability and learning effectiveness remain gap #6.

### 3. Tutor action planning and plan revision â€” implemented

**Proposal:** Sections 4.1/4.3 and B.2 specify selection by need, uncertainty, urgency and performance; multiple educational actions; a learner goal; and a versioned `revise_plan` operation.

**Implemented:** Owner/course-scoped learning goals and current plans, with immutable revision snapshots. `core/planning.py` filters prerequisites and ranks eligible actions using explicit need, uncertainty, review urgency, recent performance and goal relevance. Actions include introduction, practice, remediation, difficulty adjustment, prerequisite revisiting, target reassessment and advancement to related concepts. Goal-scoped planning includes unmet prerequisite ancestors. The Tutor model chooses from at most twelve highest-ranked validated candidates and returns a learner-facing rationale; invented candidate IDs are rejected. Candidates, factors, scores, evidence references, objective, action, level and rationale are persisted with the assigned activity in one transaction. Course relationships, learner version and plan version are rechecked before commit. Existing pending work is retained; explicit learner Next still controls advancement.

`GET /api/courses/{id}/plan` and `POST /api/courses/{id}/plan/revise` expose the goal/plan contract. Revisions check ownership, operation identity, expected plan/learner versions, course-scoped activity references, prerequisites and timezone-aware review dates. Duplicate operations return the original immutable snapshot; conflicting/stale requests fail. The Tutor page provides a learning-goal editor and current-step explanation. Introductions/remediation show level-matching teaching resources before a question; practice/reassessment can proceed directly to the question. Focused sessions retain their explicit focus.

**Boundaries:** Utility weights and available actions are explicit prototype policy, not experimentally optimized. The model selects a bounded educational action; it does not execute arbitrary tools or independently write state. Goal records are per local owner/course, consistent with the current single-owner prototype. Controlled learning-quality comparisons remain gap #6.

### 4. Rubric assessment and diagnostic evidence â€” implemented for MCQs with optional written reasoning

**Proposal:** Sections 4.1-4.2 and B.2 require rubric coverage, misconceptions, response time, prior evidence and contradictions, with source-grounded assessment.

**Implemented:** New Expert questions at all three levels include private reference answers and source-backed weighted rubric criteria. Each criterion maps all four choices to bounded scores, and only the correct choice may meet the full rubric. Nested citations, reference answers and score mappings receive source-support review. Legacy questions can receive a newly authored/reviewed rubric at assignment or assessment without rewriting course packs or resetting progress.

The Assessing model receives the rubric, reference answer, actual difficulty, course passages, persisted hint use, server timing, prior level-specific evidence and up to eight previous assessments. It returns per-criterion coverage, misconception evidence, contradiction and uncertainty signals. Runtime validation requires every criterion exactly once, bounds grades by the authored choice rubric, rejects response quotes absent from the learner's actual text and rejects full credit that conflicts with a reported misconception. Choice-only grading follows the authored mapping; optional written reasoning can lower coverage, never turn a wrong choice into a correct one. Partial/uncertain/assisted answers cannot supply independent demonstrated evidence.

Assessment history retains coverage/score, misconceptions with response quotes, contradiction references, prior assessment IDs, optional reasoning and timing. Difficulty-specific aggregates append evidence references. Two later independent qualifying answers resolve a recorded contradiction while keeping its history. Server presentation/assignment-to-submission elapsed time is recorded separately from model latency; unknown legacy timings stay unknown. Timing qualifies feedback context and does not grant correctness or mastery. The UI provides optional answer explanations and expandable rubric coverage.

**Boundaries:** Activities remain four-option MCQs, with optional written reasoning. General standalone essay questions are not implemented. Semantic rubric/diagnostic quality remains a model judgment requiring independent evaluation (gap #6). The distinct confirmed-weakness transition is implemented under item #5.

**Validation for items 3â€“4:** 111 backend tests pass, including an isolated forward-migration preservation test; 43 frontend tests and type checks pass. Tests cover utility factors, goal/prerequisite routing, plan version races, operation replay, invalid references, private-key protection, legacy rubric authoring, optional reasoning, partial evidence, exact response quotes, timing, prior evidence and contradiction history. See `planning-assessment-validation.md` for live-service validation and operational notes.

### 5. Confirmed weakness has a distinct transition â€” implemented

**Proposal:** Section 4.2 and C.1 distinguish an inconclusive contradiction (`review_due`) from confirmed weakness (`developing`), while retaining earlier evidence.

**Implemented policy:** After a previously demonstrated level, the first certain independent rubric failure schedules review. Two consecutive, distinct, unassisted and certain rubric failures at that same difficulty confirm weakness and move the level to `developing`. A wrong answer or incomplete rubric coverage can be a failure; ambiguous/uncertain or hinted responses cannot count toward confirmation. Success, uncertainty or assistance interrupts the failure streak. Duplicate activity IDs cannot supply the second failure. The threshold is the explicit `WEAKNESS_FAILURE_THRESHOLD = 2` prototype policy; the proposal itself does not prescribe a number.

Current qualifying successes remain separate from lifetime independent-success history. Confirmed weakness records retain activity and assessment references, confirmation time, resolution metadata and episode history. Contradiction records become `confirmed_weakness` without deleting prior assessments. Two fresh independent rubric-meeting responses at the affected level restore demonstration and resolve the episode; lower-level success cannot clear higher-level weakness. Prerequisite gating follows the resulting target-level state. Tutor difficulty adjustment provides remediation after confirmation. Assessment feedback and activity traces distinguish uncertainty, contradiction, confirmation and recovery.

**Compatibility:** Existing records are handled lazily on their next assessment, without inferring missing historical failure counts. Saved submissions remain unchanged. No migration or course reset is needed.

**Verification:** 123 backend tests and 44 frontend tests pass. New cases cover distinct/replayed failures, interrupted streaks, uncertainty, assistance, partial rubric failures, expired/legacy review, repeated weakness episodes, recovery and prior-history preservation. An isolated PostgreSQL/API sequence covers demonstration -> first error/review -> confirmation/developing -> Basic remediation -> two fresh target-level successes, with dependent concepts blocked until recovery. Replaying an assessment leaves evidence unchanged. See `confirmed-weakness-validation.md`.

### 6. Controlled research evaluation infrastructure â€” implemented; study pending human review

**Proposal:** Section 5 and C.2 require three variants per agent/27 combinations, four controlled pseudo-student profiles, pre-test initialization, hidden simulator state, independent unseen post-test scoring, frozen resources per Expert variant, repeated controlled runs, and fixed-sequence/no-cross-session-memory baselines.

**Implemented (3 November 2026):** `learnloop/evaluation/` provides a file-isolated batch harness. Three Expert, Tutor and Assessor prompt emphases share schemas, model settings, source gates, runtime policies and budgets. Four seeded hidden pseudo-student profiles retain private ability/misconceptions/memory; Tutor/Assessor never receive that state. Pre-tests initialise estimates without independent demonstration credit. Separate post-tests stay out of teaching/retrieval and are scored independently using frozen source-backed MCQ keys/rubrics. Only actual teaching/hints/feedback can update simulator learning.

The runner freezes each Expert graph/resource pool, checks hashes/source receipts and test overlap, uses simulated session/review time, and implements matched fixed-sequence and memory-free baselines. Manifests bind source code, prompts, models, seeds, resources and configuration. Completed episodes resume without paid calls; failed attempts restart explicitly from the initial profile, retaining checkpoints and enforcing a three-attempt cap. Call/token reservations and sanitized provider usage/cost/latency logs cover experiments without changing the production transport. Reports include independent learning/state/trajectory metrics, matched factorial contrasts and a quality/token/latency frontier. Research episodes with inadequate simulator policy agreement are excluded rather than reported as valid research scores.

Multi-model judgments, agreement and bge-m3 cosine screening flag resources. Research runs require hash-current human review of the unit/exams, every Expert graph, all flags and a deterministic unflagged sample. The CLI records human-asserted findings; it never invents approvals. Offline fixtures and canaries cannot substitute for research artifacts.

**Prepared artifacts:** A 12-concept COMP7608B unit, 72 distinct pre/post questions, all three live Expert variants (36 source-reviewed resource packs), and screening by `openai/gpt-6-luna` and `google/gemini-2.5-flash` with bge-m3. An evaluation-only citation correction and retained exam provenance are documented; production course data was not modified. Screening flagged **10 packs**. **18 grouped human review records** remain required, including the complete exam bank and unit; none are recorded. The private readable handoff is `../evaluation/comp7608b-inference-v2-draft/review-packet-002.md`.

**Verification:** **169 backend tests passed**, including 20 evaluation tests. A full offline 27Ã—4Ã—2 matrix completed **216 episodes**, plus **24** matched baseline episodes, without workflow failures. These are explicitly `workflow_only`, not learning-quality evidence. A live one-concept canary completed real source review, Tutor/Assessor/Simulator calls and independent scoring with 100% controlled-response agreement; its small-sample scores do not establish learning gains. See `evaluation-harness.md` and `../../tmp/evaluation-validation-final/validation-report.md`.

**Remaining research execution:** A human must inspect and record the pending review items, then run the paid controlled comparisons and interpret results. Simulator assumptions, grading/difficulty quality, false-demonstration rates and attrition still need scientific scrutiny. The software harness is implemented; the full research study and human learning-effectiveness claims are not complete.

### 7. Usage accounting and total execution budgets are incomplete â€” medium/high priority

**Proposal:** Sections 4.3, 5.4 and C.1/C.2 require token/cost traces, per-agent latency summaries, and turn/token limits.

**Code:** `services/clients.py:167` caps output tokens per request and `:202` returns only parsed model content; provider usage/cost is not retained. Runtime events include timestamps and state changes, and worker attempts/timeouts are bounded. No cumulative episode token/cost/turn budget, per-agent usage ledger, or median/p95 reporting was found.

**Needed:** Capture usage and latency for each provider call (including retries), attribute to agent/run/variant, enforce aggregate limits, and report preparation separately from tutoring. Timestamped activity events are useful but insufficient for the promised cost evaluation.

### 8. LangGraph and reproducible container deployment are absent â€” medium priority

**Proposal:** Section 4.4 specifies one LangGraph workflow and Docker Compose.

**Code:** `runtime/workflows.py:16` is a Python dispatch registry. Durable SQL jobs/checkpoints already provide substantial recovery behavior, but there is no LangGraph dependency or StateGraph. No Dockerfile/Compose configuration was found in the project search.

**Needed:** Implement the specified orchestration/deployment stack, or explicitly revise the proposal to describe the working custom runtime. Adding LangGraph alone does not supply the missing pedagogical decisions.

### 9. Validated, versioned knowledge-base publication — implemented

**Proposal:** A.2 describes validating graph and resources before publishing a versioned course knowledge base.

**Implemented (4 November 2026):** Concept discovery now stages documents as `prepared`. The Expert completes course-wide organization, curriculum and every resource pack before `publish_course` validates and atomically appends a `CourseRelease`. Validation requires complete source analysis, current organization/curriculum, prerequisite consistency, distinct teaching scopes, current material/source receipts, private rubrics/reference answers, two questions at each assessment difficulty, distinct prompts, and a lesson scope receipt bound to its current objective. The existing curriculum uses one scoped primary lesson per objective; its layer remains separate from the three quiz difficulties.

Each release freezes the combined graph, document graphs/resources, source text/page metadata, document hashes and a content hash. Publication takes course/document/source locks; concurrent retries reuse an identical latest release. A failed or incomplete rebuild preserves the prior ready version. ORM updates/deletes are rejected, and reads verify snapshot integrity. Learner graph/material/search reads use released snapshots. Preparation checkpoints remain mutable and resumable.

New study sessions pin the ready release; older unpinned sessions acquire a pin on their next learning action. Tutor planning, prepared questions, retrieval, chat and assessment resolve the pinned graph/resources/sources, including after a newer publication. Session responses expose the release ID; activities retain it privately. Legacy configurable targets are stored in learner plan revisions rather than changing released content. Owner-scoped release metadata and an explicit validated publication endpoint are available; private quiz banks never appear in those responses.

Evaluation export now accepts `--release`, defaults to the latest complete release and writes hash-bound release provenance into the experiment manifest. Existing curated evaluation bundles remain standalone frozen research artifacts; this update does not retroactively claim a production release for them.

**Rollout:** Additive migration `0003` creates releases and a nullable session pin without deleting courses, uploads, responses or learner evidence. It does not silently approve/backfill older resources. Existing courses must finish source/scope revalidation and publish their first release before the updated learner endpoints expose them. See [course release guide](course-releases.md). Application services have not been restarted and the production migration has not been applied by this implementation task.

**Verification:** **183 backend tests pass** with integration checks enabled; lint and formatting pass. Eleven release-specific cases cover incomplete/stale preparation, atomic/idempotent/concurrent publication, rollback, pinned sessions and assessment, ownership/privacy/integrity and release-based evaluation export. The migration preservation test includes `0003`; evaluation tests additionally reject changed release provenance on resume. No production content or learner evidence was reset.

### 10. Shared multi-learner use and supporting rewards remain incomplete â€” lower priority

The proposal describes one shared published course graph with separate learner evidence. Evidence records include owner/course separation, but the API is explicitly a local single-owner prototype (`backend/README.md`); real learner enrollment/access to a shared course is not implemented. Missions/rewards were not found as functional persisted features. Concept learning objectives and ordinary status badges do not establish learner goals or gamification. These are secondary to the learning and evaluation gaps; optional external enrichment is explicitly excluded from the prototype and is not missing required work.

## Verification performed

- Initial review baseline: default suite **32 passed, 24 skipped**; with `LEARNLOOP_INTEGRATION_TESTS=1`, **56 passed**.
- After implementing gap #1: **76 passed** with integration tests enabled. Changed Python files pass Ruff lint and formatting checks. PostgreSQL fixtures create and remove isolated `ll_test_*` schemas and use fake model/vector providers; no paid generation calls.
- Initial read-only probes reproduced repeated-error behavior and acceptance of a graph with an unknown source ID. The public reference projection now rejects unknown/empty sources; regression tests cover the new behavior. The repeated-error transition was unchanged in the initial source-support fix and is now addressed under item #5.
- One existing Starlette/AnyIO deprecation warning. No live learning-quality experiment or human learning study was performed.

## Suggested implementation order

1. Independently evaluate the implemented source/rubric gates and the now-explicit weakness/recovery policy.
2. Add call-level telemetry, aggregate budgets and complete resource releases (gaps #7/#9).
3. Complete human review of the prepared evaluation bundle, then run the proposed comparisons using the implemented harness and baselines (gap #6).
4. Reconcile LangGraph/deployment promises and implement multi-learner/reward features as required by final scope (gaps #8/#10).

Evaluation implementation update, 3 November 2026: no SQL migration or app-service restart was required. The existing backend regression suite passes with the evaluation package installed.

Evaluation continuation, 4 November 2026: `status --bundle PATH` now checks artifact integrity, screening and all required human review records without loading service credentials or writing files. Optional `--model` and `--temperature` check the intended run against frozen Expert settings. Non-ready bundles return exit code 1. Human inspection and research execution remain pending.

Continuation verification: **171 backend tests passed**, including **22 evaluation tests**; lint and formatting pass. Read-only inspection of the prepared live bundle confirms current artifacts/screening and matching model settings, with all 18 required human reviews pending. No new paid research run was dispatched.
