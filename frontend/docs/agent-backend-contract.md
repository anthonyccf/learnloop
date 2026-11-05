# Agent activity backend handoff

Status (18 October 2026): the first FastAPI backend implements these v1 run endpoints with bearer authentication. See `../../backend/README.md` for the runnable API, worker, uploads, sessions and assessments. The frontend still constructs DemoAgentSource. Connect through a same-origin server proxy that holds the backend token privately and forwards SSE; native EventSource cannot supply bearer headers. Inject the live source only after that bridge exists, label transport mode accurately and remove demo-only controls. Connect the practice provider separately. The sections below retain the original contract and production requirements; the backend README identifies implemented local-pilot scope and remaining work.

## Responsibilities

- Expert: prepare concepts, prerequisite edges and learning resources grounded in authorized course documents. Runtime owns resource publication.
- Tutoring: load authoritative learner evidence, select eligible activities, retrieve explanations and revise the plan.
- Assessing: assess submitted responses, distinguish hinted evidence from independent evidence and propose changes. Runtime owns learner-state commits.
- Runtime: authentication, scoped tool authorization, budgets, schema/source checks, atomic writes, version checks, checkpoint persistence and retry limits. It is not a fourth agent.

## Proposed endpoints

The factory `createHttpAgentSource('/api/agent-activity')` calls:

| Method | Path | Response |
| --- | --- | --- |
| GET | /runs/:runId | AgentRun v1 authoritative snapshot |
| GET (SSE) | /runs/:runId/events?after_sequence=N | Default message events carrying AgentEvent v1 |
| POST | /runs/:runId/commands | CommandReceipt v1 |

All payloads are defined by executable Zod schemas in `src/lib/agent-activity/contracts.ts`; TypeScript types derive from them. Publish JSON Schema/OpenAPI from these with the backend team rather than maintaining a competing handwritten schema. Snapshot fields include course/run IDs, workflow, three agent stages, current role, status, safe summary, record version, sequence cursor, checkpoint, allowed commands, validation, artifacts, references and bounded public event history.

Events carry schemaVersion, unique ID, run/course scope, monotonic sequence and UTC/offset timestamp. Types: agent.step, agent.handoff, runtime.validation, run.status. Tool names are a public allowlist, not permission to execute tools from the browser. Artifacts distinguish candidate/published/committed. Sources carry authorized document IDs and locations; fetch source content through a separate authorized document API.

SSE must replay every retained event beyond after_sequence before streaming new events. Native EventSource reconnects to the same URL; duplicate replay is tolerated. Support Last-Event-ID or an equivalent durable server cursor for efficient replay. If the cursor expired, terminate the stream and require a fresh snapshot. Missing/out-of-order events freeze frontend processing; Refresh loads a new snapshot and subscribes again. On network errors show reconnecting/offline separately from workflow status. Do not restart jobs or resubmit learner responses simply because the stream reconnects.

Retry/resume body: `{kind, operationId, expectedVersion}`. Scope operation IDs by authenticated learner/course/run. Store command result atomically and return the same receipt for repeated operation IDs; reject reuse with a different body. Only allow commands advertised by the current snapshot, enforce permission and retry limits server-side, and reject stale expectedVersion with 409. Acknowledging a command is separate from completing it; emit authoritative events for changes. The UI retains the same operation ID for an uncertain retry at the same cursor/version. No optimistic progress updates.

## Commit rules

runtime.validation pending includes scope and a proposed learner change when applicable. Accepted requires matching pending scope and previousVersion, advancing the workflow recordVersion by one. For learner_state it also includes the matching committed change and authoritative learnerVersion. The backend must atomically persist evidence and its versions before emitting accepted. Rejection leaves evidence unchanged. Separate activity validation can advance workflow version without changing learner evidence.

When integrating practice, submit activity ID, response, stable operation ID and expected learner version. Persist hint usage on the server. Never accept correctness, learner identity, mastery state or answer keys from the client as authority. The public assessment event contains learner-safe feedback and uncertainty, not hidden rubric/answer keys before submission. After accepted learner evidence, reconcile the graph and Progress from the authoritative learner-state endpoint; do not infer mastery from agent narration or an activity assignment.

## Remaining backend work

Run creation/listing and reconnect discovery by course/session, activity/response APIs, authorized resource lookup, ingestion/publication, learner-state reconciliation, auth expiry, access review, operational metrics, cancellation, persistence, real agent orchestration and staff review actions are not implemented. Review scenarios are read-only; the frontend does not approve or publish flagged resources. Server timing/token/cost data can be added to the schema when available; the demo invents no live metrics or completion estimates.

Use same-origin authenticated endpoints with CSRF protection for commands; credentials remain server-side. Server derives learner identity and validates course membership on snapshots, streams and commands. Display summaries should be generated from an explicit safe projection of runtime records. Strict parsing limits do not replace backend authorization. Production transport should be tested for replay retention, disconnect during commit, snapshot/event races, expired auth, version conflicts and duplicate commands.
