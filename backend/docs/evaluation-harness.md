# Controlled evaluation harness

Implemented for proposal gap 6. The package is `learnloop/evaluation/`; it uses files in explicit experiment directories and never writes to application SQL or Qdrant. Only `export-unit` opens SQL, in a read-only transaction. No API migration, worker restart or course reset is needed.

## What is implemented

- Three Expert emphases (structural, grounded, verified), three Tutor prompts (state, graph, utility) and three Assessor prompts (correctness, evidence-weighted, conservative): all **27 combinations**. Model, temperature, schemas, permissions, source data, activity limits and runtime rules remain fixed across variants. Production schemas, source gates, candidate policy, rubric validation and learner transitions are reused; SQL job orchestration is deliberately outside the experiment adapter.
- Four pseudo-student profiles with separate hidden initial difficulty-specific ability, misconception state, hint dependence, response characteristics, bounded learning updates and private memory. Seeded draws are paired across conditions/profile/repeat. LLM students see public questions and actual teaching/hints/feedback, never answer keys or private rubrics. Tutor/Assessor contexts never receive hidden profile/state.
- Independent pre/post MCQ exams with one question per concept at each of three levels. Pre-test scores initialise developing estimates without independent demonstration credit. Held-out prompts/keys are never sent to Expert/Tutor or experimental Assessor; the test author is a separate context. Post-test scoring uses the frozen source-backed key/rubric, independently of the experimental Assessor.
- Expert graphs, teaching resources and pools are prepared once per variant and hash-bound to unit/exam/configuration metadata. Experimental tutoring cannot generate fallback questions or mutate the frozen pool. Exact training/test prompt overlap and repeated question IDs are rejected. Semantically similar or near-duplicate questions still require human review.
- Repeated seeded episodes, simulated sessions and an eight-day default gap exercise seven-day review. A fixed-sequence baseline retains assessment/persistence with prerequisite-respecting order and a fixed Basic/Intermediate/Advanced progression. The memory-free baseline restores the original pre-test estimates and clears teacher history/plans at session boundaries while retaining the pseudo-student's learning. Runtime question-ID deduplication persists for all conditions; it is not used as learner evidence.
- Append-only result artifacts, source/config/prompt hashes, usage ledgers and per-turn hidden checkpoints. Completed episodes resume without additional model calls. Interrupted episodes restart from the same initial state only with `--retry-failed`; attempts are retained and limited to three. Mid-episode continuation is not claimed. Runtime code changes invalidate a running episode or resume manifest.
- Call/token reservations, activity/call limits, bounded source repairs, provider-reported cost and latency. Missing token usage stops a live run; unavailable monetary cost stays unknown. Preparation is reported separately from episode use. Optional bounded preparation workers statically partition remaining budgets rather than multiplying the budget.
- Multi-model judgment and agreement, embedding cosine screening, and hash-bound human review records. Research execution requires two distinct configured screening models, current screening, human review of the unit/exam bank/all Expert graphs, every flagged resource and a deterministic 10% unflagged sample (at least one per variant). The CLI records a human's asserted review; it cannot establish that a person actually inspected the material. No approvals are automatically created.
- Pre/post performance, independent post-test mastery, learning gain per activity, target attainment, learner-state macro F1, difficulty-state accuracy, false demonstration, misconception precision/recall, policy violations/redundancy/recovery, model usage/cost and per-role median/p95 latency. JSON/Markdown reports include descriptive main/pairwise/three-way gain contrasts only for matched complete 27-cell data, and a quality/token/latency Pareto frontier.

## Prepared course unit

`backend/evaluation/comp7608b-inference-v2-draft/unit.json` contains 12 concepts from the supplied COMP7608B Lecture 2: floating-point representations, quantization, mixed precision and attention/prefill foundations. Passage metadata retains document name/page and the original document hash. The corrected evaluation copy includes the matching page for common quantization mechanisms; no production citation was changed. `curation.json` records the correction and verified retention of the 72 already model-reviewed pre/post questions. Human review remains pending.

The initial `comp7608b-inference-draft` is retained for provenance; it is superseded by v2. Preparation stopped rather than accepting the initial unsupported citation. Use v2 for subsequent work.

## Commands

Run from `E:\agentic-learning\backend` with `.venv\Scripts\python.exe`:

```powershell
# Read-only readiness check; exit code 1 lists blockers, 0 means bundle gates pass.
# No credentials or paid calls. Add --model ACTUAL_MODEL to check intended settings.
python -m learnloop.evaluation status --bundle evaluation/comp7608b-inference-v2-draft

# Complete/resume real preparation. Completed concepts/artifacts are retained.
python -m learnloop.evaluation prepare --bundle evaluation/comp7608b-inference-v2-draft --stage all --workers 2

# Independently screen with two real provider-supported model IDs.
# Supply their actual IDs; PRIMARY_MODEL and SECOND_MODEL below are placeholders.
python -m learnloop.evaluation screen --bundle evaluation/comp7608b-inference-v2-draft --models PRIMARY_MODEL SECOND_MODEL
python -m learnloop.evaluation review-packet --bundle evaluation/comp7608b-inference-v2-draft

# A HUMAN performs the inspection, then records each required approval/rejection.
python -m learnloop.evaluation record-review --bundle evaluation/comp7608b-inference-v2-draft --item unit --reviewer "Actual reviewer" --decision approved --notes "Actual findings and checks performed"
# Repeat for exams, Expert graphs, flagged resources and the unflagged sample.

# All 27 configurations, four profiles, two repeats: short live screen.
python -m learnloop.evaluation run --bundle evaluation/comp7608b-inference-v2-draft --output ../tmp/evaluation-real-screen --activities 6 --repeats 2

# Repeated full evaluation / matched baselines for an explicitly retained condition.
# grounded/utility/weighted is an EXAMPLE, not a research winner.
python -m learnloop.evaluation run --bundle evaluation/comp7608b-inference-v2-draft --output ../tmp/evaluation-real-baselines --selected grounded utility weighted --baselines --activities 24 --repeats 3
```

The primary model uses the existing backend configuration. Requests retain model, seed and temperature, and ledgers record the provider's resolved model identity. Hosted-model seeds are best effort; they do not guarantee bitwise reproduction. Select a version-pinned model for the actual study and inspect resolved model identities before pooling results.

`--max-calls` and `--max-tokens` bound each episode; `prepare --max-tokens` bounds each preparation attempt (three attempts maximum per stage). No full paid matrix is launched automatically by installation or app startup.

To reproduce the **offline workflow check** without credentials/model calls:

```powershell
python -m learnloop.evaluation prepare --bundle evaluation/comp7608b-inference-v2-draft --offline
python -m learnloop.evaluation run --bundle evaluation/comp7608b-inference-v2-draft/offline-fixtures --output ../tmp/evaluation-offline-new --offline --activities 6 --repeats 2
```

Offline fixture questions intentionally have obvious answers and fixture providers ignore prompt emphasis. Their apparent gains/effects are not evidence about the agents. Artifacts carry `workflow_only`, and research runs reject them. Use a fresh output directory when code/configuration/resources change.

For a small live protocol check without claiming a research result:

```powershell
python -m learnloop.evaluation canary --bundle evaluation/comp7608b-inference-v2-draft --output ../tmp/evaluation-canary-new
```

This generates separate one-concept exams and teaching resources, then exercises real Tutor/Assessor/Simulator calls. The original 12-concept unit remains intact. Canary artifacts carry `canary` and cannot substitute for a reviewed 10â€“20-concept research bundle.

## Interpretation limits

The hidden ability thresholds and learning/forgetting caps are explicit simulator assumptions, not a validated human learner model. `simulationPolicyAgreement` records whether actual answers followed the controlled ability draws; imperfect agreement must be examined and calibrated before using latent-state accuracy as research evidence. A passing workflow canary does not validate simulator fidelity, grading quality, appropriate difficulty or learning gains.

There is one held-out item per concept/level in each exam, so concept mastery estimates are noisy. `activitiesAtVerifiedTarget` is endpoint-censored: it reports the activity count when the final unseen post-test verifies the target, not the unobserved earliest possible mastery time. Failed/budget-stopped episodes remain reported but are excluded from score means; review attrition before comparing conditions. Factorial contrasts are descriptive, not statistical significance tests. The frozen pool can be exhausted; no new teaching questions are generated during an episode.

This implements experiment-level accounting/budgets. Production-wide accounting remains proposal gap 7. Full controlled comparisons, human review, simulator calibration and interpretation are research execution work, not automatically established by the software tests.

## Validation recorded on 3 November 2026

- 169 backend tests pass, including 20 evaluation-specific tests. Lint and formatting pass.
- The current-code offline matrix completed 216 episodes (27 Ã— 4 Ã— 2), plus 24 matched baseline episodes, without workflow failures.
- The live one-concept canary completed with 100% controlled-response agreement and no prerequisite/state-update violations. Its post-test score was lower than its pre-test score, demonstrating why a workflow check must not be presented as learning-effectiveness evidence.
- All three live Expert variants are frozen. All 36 packs were screened by the configured primary model and Gemini 2.5 Flash, with bge-m3 embeddings. Ten packs were flagged; 18 grouped human review records are pending.
- Read `../../tmp/evaluation-validation-final/validation-report.md` and `../evaluation/comp7608b-inference-v2-draft/review-packet-002.md`. No approvals are recorded and no full paid research matrix was executed.

Research-mode episodes require at least 75% agreement between actual student answers and their controlled ability draws (`minPolicyAgreement`, fixed in the manifest). Noncompliant episodes retain their diagnostics but are labelled `simulation_invalid` and excluded from score averages. This threshold is a prototype protocol choice, not proof of simulator calibration.

## Readiness check added on 4 November 2026

The `status` command uses the same research requirements as the runner. It lists every required review as pending, stale, rejected, incomplete or approved, reports missing/corrupt artifacts, and optionally checks model/temperature compatibility. It neither writes files nor loads provider credentials. Without `--model`, `modelChecked` is false and `ready` refers only to bundle readiness; the runner still validates its actual model settings. Status does not establish simulator fidelity or learning effectiveness.

Validation: all **171 backend tests pass**, including **22 evaluation tests**; Ruff lint and formatting pass. Tests exercise readiness with test-only approval/rejection records, stale hashes, missing/corrupt files, model mismatch, and credential-free CLI failure. The prepared live bundle passes artifact/screening validation and matches `openai/gpt-6-luna` at temperature 0.2; its 18 human reviews remain pending. No new paid study or model calls were made for this continuation. The 3 November matrix and canary records above describe their original runtime hash; changed code requires a fresh experiment output directory.

## Production release provenance

New `export-unit` operations read a complete immutable production release. Pass `--release UUID` to select a historical version; otherwise the current complete release is used. `release-provenance.json` records the release ID/version/hash and exported unit hash. Bundle loading rejects a mismatched unit hash, and experiment manifests bind this provenance so resume cannot switch releases. Existing manually curated bundles retain their original frozen provenance; no release ID is inferred for them.
