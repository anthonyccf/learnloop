# LearnLoop Agent Workbench Plan

Status: proposed product and implementation plan. This document describes a separate developer-facing website for developing, inspecting, and evaluating LearnLoop's Expert, Tutoring, and Assessing agents. It is not a learner-facing feature and does not train model weights.

## 1. Goal

Provide a focused web workspace where developers can select a course and its learning materials, edit agent prompts and model settings, run one agent or a complete learning loop, and inspect exactly what happened. Each run should make agent inputs, outputs, skill/tool operations, time, token use, and estimated cost visible and reproducible.

The current learner interface is optimized for studying, not agent assessment. The workbench should make experimentation understandable without requiring developers to edit source files or infer behavior from the learner UI.

## 2. Fit with the existing project

LearnLoop already has three production agent workflows in `backend/`, a Python-only `agent_lab/` for prompt/model experiments, and an evaluation harness with per-role token, cost, and latency ledgers. The workbench should add a web control and inspection surface over these existing capabilities rather than create a second implementation of agent behavior.

- Reuse the backend's Expert, Tutoring, and Assessing entry points, schemas, validators, repositories, and workflow events.
- Reuse or extend `agent_lab/` configuration and isolated database behavior for safe experiments.
- Reuse evaluation ledger concepts for run metrics and comparisons.
- Keep learner-facing behavior and staff experiments separate. Workbench drafts must not silently alter production prompts or learner records.
- Clearly label current production behavior, workbench draft behavior, and mock/sandbox behavior.

## 3. Main developer workflow

1. Open the workbench and select **Expert**, **Tutor**, **Assessing**, or **Full learning loop**.
2. Select a course, then select one or more materials from that course. Show material processing/publication status and source identity.
3. Choose the learner/session context when running Tutor or Assessing. For a full loop, allow an isolated learner profile or a generated test learner.
4. Edit or select a prompt version, model, and run limits. Show which settings are drafts and which version is currently saved.
5. Run the agent or loop. Display live progress, elapsed time, current step, and budget consumption.
6. Inspect the trace, final result, and any warnings or errors. Expand each model call and skill operation to see its inputs and outputs.
7. Save the configuration as a version, compare it with another run, or restore a previous version.

## 4. MVP screens and layout

### Workbench / run console

Use a practical three-column desktop layout; responsiveness is useful but visual polish is secondary.

| Area | Contents |
| --- | --- |
| Left rail | Agent selector, saved configurations, recent runs, saved scenarios |
| Setup panel | Course and material selectors, learner/session context, prompt editor, model settings, budget limits, Run button |
| Results panel | Live status, final output, timeline, model-call and skill traces, metrics, errors, and comparison controls |

On smaller screens, stack these areas into Setup, Run, and Results tabs without losing selected context.

### Course and material selection

- Course is a searchable select menu populated from the developer's authorized courses.
- Materials selector is scoped to the chosen course and supports selecting one or multiple documents/materials.
- Show title, material type, processing state, publication/release state, and last updated time in each option.
- Disable materials that are not ready for the selected workflow, explain why, and offer an explicit option to include draft/unpublished material in an isolated experiment where supported.
- Changing the course clears incompatible materials and learner/session context with a visible indication.
- Show the exact selected course/material IDs and release/version in the run record for reproducibility.
- Expert runs may use selected source materials to prepare or reprocess course content. Tutor runs use the selected published course context and can optionally narrow context to selected materials. Assessing runs use the assigned question, learner answer, and associated source materials; allow a material override only as an explicit diagnostic setting.

### Agent configuration

Allow prompt editing and model settings by agent. At minimum expose:

- Prompt template/editor and current saved version.
- Model/provider identifier, temperature or equivalent sampling setting, output token limit, and request timeout where supported.
- Enabled skills/operations for the run, shown with a short description and input/output schema.
- A context preview showing what will be sent to the agent, with sensitive fields identified and editable test fixtures where safe.
- Save as draft, duplicate version, compare versions, and restore actions.

Do not imply that prompt/model settings override deterministic runtime validation, grading keys, eligibility rules, or evidence commits. Make those runtime-owned rules visible as guardrails in the trace.

## 5. Budgets, elapsed time, and cost

Budget and timing information should be available before, during, and after execution. Track per model call, per agent, and for the complete loop.

### Before a run

Allow the developer to set optional hard limits:

- Maximum elapsed time for the whole run.
- Maximum elapsed time for an individual agent or model request.
- Maximum input and output tokens per request and/or cumulative tokens for the run.
- Maximum estimated model spend for the run.
- Maximum retries and skill/tool calls.

Show model/provider limits and any configured defaults. Where a reliable estimate is unavailable, label it as unknown rather than inventing a precise estimate. For repeatable scenarios, show historical median and p95 duration and typical token/cost range, clearly marked as historical estimates.

### During a run

Show a compact live budget bar and elapsed timer, with:

- Total elapsed wall-clock time, including queue/wait time where applicable.
- Active agent and current workflow step.
- Input/output tokens and estimated cost so far, with per-agent breakdown.
- Model request duration, retrieval/skill duration, retries, and remaining hard limits.
- Clear warnings near limits and a stop/cancel action when supported.

Timing should distinguish queue wait, preparation/retrieval, model-call time, validation/persistence, and total end-to-end time. An ETA is a rough estimate only; present it only when prior comparable runs support one.

### After a run

Show total elapsed time, queue time, agent durations, model-call durations, retry count, input/output tokens, and estimated cost. Provide a table with one row per agent and expandable detail per model call/skill operation. Identify incomplete measurements, provider-reported values versus locally estimated values, and calls that failed before usage was returned.

Budget exhaustion should stop further optional model/skill work cleanly, preserve the trace and completed checkpoints, and report which limit ended the run. For operations that cannot be interrupted mid-request, explain that the active request may finish before the limit takes effect.

### Suggested metrics model

Each run should have a run ID and immutable snapshots of selected course/material versions, agent config versions, and limits. Record timestamped events with agent, step, operation, status, start/end time, duration, retry number, token counts, estimated cost/currency, provider/model, and trace correlation ID. Never report an estimated cost as an exact provider charge.

## 6. Trace and output inspection

The run view should provide a chronological event timeline, grouped by agent and step. For each event, show:

- Agent, step name, operation/skill name, and status.
- Input/context and output, with JSON formatting for structured values.
- Model/provider, prompt/config version, and schema where relevant.
- Start/end timestamps, duration, token usage, and estimated cost when available.
- Validation result, retry/fallback details, and error message when applicable.

Support copy/export of a redacted run record for debugging. Preserve private answer keys and credentials: do not expose secrets in the UI or exported traces. For Assessing, show the learner answer and feedback path, but keep hidden grading data behind explicit developer access controls and never include it in ordinary learner-facing outputs.

## 7. Full-loop scenario

The full-loop runner should make the LearnLoop sequence testable from one page:

1. Expert prepares/validates selected course materials or reuses an existing published release.
2. Tutor reads the selected course release and learner state, chooses an eligible activity, and returns a question/lesson action.
3. The test learner supplies a configured or manually entered answer.
4. Assessing evaluates the answer, returns feedback, and produces the validated evidence transition.
5. The run summary shows the updated sandbox memory and the next Tutor decision, if requested.

Allow single-agent runs as well as the full loop. The tester should be able to pause between steps, edit the simulated learner answer, and continue. Make explicit when existing course artifacts are reused versus regenerated.

## 8. Safety, isolation, and reproducibility

- Default to sandbox/test learner state; never mutate a real learner's progress from a workbench run.
- Require a clear, separate action to publish a prompt/config version to a shared environment. Show a diff and affected agent before publication.
- Version prompts and model settings immutably; every run references the exact versions used.
- Use existing backend authorization and course ownership checks for course/material menus.
- Mask API keys and secrets. Redact sensitive fields from trace exports.
- Make database writes, course publication, and other side effects visible before execution; disable them by default in isolated runs unless needed for the experiment.
- Preserve run traces and checkpoints after failures and budget exhaustion so runs can be diagnosed or resumed safely.

## 9. Evaluation and comparison

Let developers save scenarios with course/material selection, learner state, input, expected behavior, and optional rubric. Run the same scenarios against two configuration versions and compare:

- Output differences and structured schema/validation outcomes.
- Learning decision (for example, consolidate versus increase difficulty).
- Source grounding and selected course/material references.
- Latency, token use, estimated cost, retries, and failure rate.
- Human reviewer rating, when supplied.

Aggregate latency should include median and p95, not just the fastest run. Keep evaluation results distinct from evidence that a configuration improves learning outcomes; that requires a deliberate study and reviewed measures.

## 10. Implementation phases

### Phase 1: Inspectable single-agent runs

- Add/confirm a stable trace event contract for model calls, retrieval, skill operations, validation, and persistence.
- Build the standalone workbench run console for one agent.
- Add course and material selectors and context preview.
- Show prompt/model configuration and final input/output.

### Phase 2: Budget and timing instrumentation

- Record per-call and per-agent durations, tokens, provider/model, retries, and estimated cost.
- Add configurable hard limits, live run metrics, warnings, cancellation where supported, and a run summary.
- Reuse the evaluation harness's ledger/reporting concepts where practical.

### Phase 3: Full learning loop and safe learner simulation

- Add Tutor and Assessing test context, sandbox learner state, step-by-step continuation, and end-to-end traces.
- Add saved scenarios and repeatable run configuration snapshots.

### Phase 4: Version comparison and team workflow

- Add immutable draft versions, run-to-run comparison, evaluation batches, reviewer annotations, and controlled promotion/rollback.
- Add role-based access only as required by the deployment audience; preserve current single-owner assumptions for a local pilot.

## 11. Acceptance criteria

The MVP is ready for internal use when a developer can:

- Select an existing course and one or more materials and see their readiness/version details.
- Run each agent independently with a visible prompt, model, and context snapshot.
- Run a complete isolated Tutor → Assessing loop, with Expert preparation available for selected materials.
- Inspect each input, output, model call, skill operation, validation, error, and retry in order.
- See elapsed time and token/cost measurements per operation, agent, and full loop, with estimates labeled accurately.
- Set run limits and receive a clear result when a limit is approached or reached.
- Save and compare configuration versions without changing the learner-facing production configuration.
- Reproduce a run from its saved course/material, learner fixture, configuration, and budget snapshot.

## 12. Open implementation decisions

Resolve these during technical design, using existing project patterns where possible:

- Whether the workbench is a new route group in the existing Next.js app or a separately deployed frontend. The product boundary is separate from the learner experience either way.
- Which trace events can be emitted by the current provider client and worker without changing agent semantics.
- Which provider usage fields are available for exact token/cost reporting, and how local estimates are calculated when they are not.
- Whether sandbox runs use a dedicated database/schema or transactional test fixtures.
- Which actions can be cancelled safely and which can only stop after the current model call.
