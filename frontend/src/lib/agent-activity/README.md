# Public agent activity

This folder describes and displays agent execution. The three executing agents are in [`backend/learnloop/agents/`](../../../../backend/learnloop/agents/).

- `contracts.ts`: public run/event schemas and role IDs; the backend JSON Schema is exported from these definitions.
- `reducer.ts`: validate and apply public events to UI state.
- `http-source.ts`: backend snapshot, event-stream, and command adapter.
- `demo-source.ts`: isolated fixtures used by the existing adapter tests; live application routes use backend records.

Run `backend/scripts/export-contracts.ps1` after an intentional schema change. A folder move does not require changing the event protocol or role IDs.
