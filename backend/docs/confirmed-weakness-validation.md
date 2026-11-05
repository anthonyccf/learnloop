# Confirmed weakness and recovery

Implemented proposal gap 5 on 23 October 2026.

## Fixed transition policy

The proposal distinguishes inconclusive contradictions from confirmed weakness but does not set a numeric threshold. This implementation fixes `WEAKNESS_FAILURE_THRESHOLD = 2` in `core/domain.py`:

1. At a previously demonstrated difficulty, the first certain independent rubric failure moves progress to `review_due`.
2. A second consecutive failure on a distinct activity at that same difficulty confirms weakness and moves progress to `developing`.
3. Incorrect choices and partial rubric coverage can qualify as failures only after source/rubric validation, without hints or assessment uncertainty. A correct full-rubric response with an unresolved model contradiction remains uncertain, not a confirmed failure.
4. A success, uncertain assessment or hinted response interrupts the failure streak. Repeating an activity cannot supply a second distinct failure. Uncertainty alone never confirms weakness.
5. Two fresh independent rubric-meeting responses restore demonstration at the affected level. Assistance cannot supply recovery evidence. A subsequent failure or uncertainty resets the qualifying recovery window. Lower-difficulty success leaves higher-difficulty weakness untouched.

For levels never demonstrated, failures remain developing evidence and do not claim a downgrade of earlier mastery. Time-based review alone also does not establish weakness.

## Evidence retention and behavior

- `independentActivityIds` contains only the current qualifying window; `independentHistoryActivityIds` retains lifetime known independent successes.
- `consecutiveFailureActivityIds` records the current confirmation streak. `confirmedWeakness` retains active/resolved status, activity/assessment references, confirmation time and recovery metadata. `weaknessHistory` retains earlier episodes.
- Existing contradiction records are marked `confirmed_weakness` after confirmation and resolved after recovery. Earlier assessment records are not rewritten or removed; already-resolved contradiction metadata is preserved.
- Assessment output exposes `evidenceOutcome` and `confirmedWeakness`. Rubric details explain confirmed weakness and recovery; Agent activity records the distinction. Map progress/prerequisite readiness already derive from target-level evidence.
- Review-due questions stay at the target difficulty. Once weakness is confirmed and progress becomes developing, existing difficulty adaptation can step down for remediation and later return to the target.

No migration, historical regrading or reset is needed. Legacy records acquire the new metadata on future assessments. Missing historical failure counts are not inferred, and saved submissions remain available even where an older aggregate lacks lifetime IDs.

## Verification

- **123 backend tests passed**, including PostgreSQL integration tests in disposable schemas. Twelve new cases exercise confirmation, duplicate failure IDs, all streak interruptions, partial/uncertain rubric evidence, legacy/time review, repeat episodes, history retention, recovery and prerequisite gating.
- The API test runs eight assessment cycles: two target successes, two target failures, two lower-level remediation successes and two fresh target successes. It verifies that dependent concepts stay blocked until target recovery and assessment replay cannot inflate counts or history.
- **44 frontend tests passed**, with type checks and lint. New rendering coverage distinguishes confirmation from review uncertainty and displays recovery guidance.
- Model outcomes are controlled for these tests because the change is a deterministic transition rule. These checks do not independently evaluate model grading quality or validate the pedagogical threshold.
