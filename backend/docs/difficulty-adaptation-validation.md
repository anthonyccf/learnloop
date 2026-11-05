> Historical validation of the earlier three-variant material system. Material version 4 now uses one primary lesson per objective in a course-wide pyramid; assessment difficulty and mastery targets remain separate. See the backend README for current behavior.

# Difficulty adaptation implementation and validation

Completed 21 October 2026 for proposal gap #2. Source-support gates from item #1 remain enabled.

New Expert packs include Basic, Intermediate and Advanced teaching posts and worked examples, plus two distinct four-option questions at each level. Question difficulty is schema-validated and stored on activities. Tutor assignment uses only matching bank entries or requests a matching fallback question; wrong-level outputs cannot be assigned.

Concept targets default to Intermediate for compatibility. Practice starts at the target, steps down one level after incorrect/uncertain/assisted evidence, and steps back up after the lower level is demonstrated. Target reviews stay at the target. Two distinct independent qualifying activities establish evidence only at their actual level. Overall concept state and prerequisite readiness use each concept's own target.

Use a concept's **Goals** tab to change its **Learning target**. The **Learning material** tab has a **Lesson level** selector. Older packs retain their existing explanation and questions; **Prepare all lesson levels** adds missing variants/questions for that material. Tutor chat selects the explanation matching its current activity. Existing saved activities and evidence are not relabeled or reset.

The target API is `POST /api/courses/{course_id}/concepts/{concept_id}/target`, with `targetDifficulty` and `expectedLearnerVersion`. Ownership and version checks apply. Changing the target increments learner-record version and preserves graph relationships and evidence. An existing pending activity keeps its original difficulty and contributes evidence at that level when assessed.

Validation:

- **91 backend tests passed**, including isolated PostgreSQL integration tests. Coverage includes lower-level success not granting a higher target, prerequisite targets, assistance/remediation/recovery, seven-day target review, target updates, wrong-level rejection, and preserving old content while adding missing resources.
- **41 frontend tests**, type checks, lint and the production build passed.
- `python -m scripts.validation.difficulty_levels` passed with real configured model/embedding/vector/database services. It generated all three lesson variants and six questions, assigned and assessed two questions at each level, and recorded independent demonstrated evidence separately at Basic, Intermediate and Advanced.
- The live test used its own `ll_difficulty_*` PostgreSQL schema and unique vector owner/document IDs. Temporary SQL/vector data was removed, and hashes confirmed unchanged existing documents, learner evidence and activities. The result is at `../../tmp/difficulty-validation/report.json`.

No database migration or destructive course reset is required. Shared old Intermediate packs remain usable; other levels can be generated on demand during practice or prepared in advance. The policy is not the broader action/plan reasoning of gap #3, and these workflow checks do not measure human learning gains or independently establish difficulty quality.
