# LearnLoop backend plan

Updated 18 October 2026. First runnable local slice implemented under `backend/`; frontend remains in demo mode.

Implemented: FastAPI, PostgreSQL, Alembic revision 0001, authenticated single-owner API, durable SQL worker, PDF/text extraction, source locations, bge-m3 embeddings, scoped Qdrant retrieval, and OpenRouter `openai/gpt-6-luna` structured generation for all three agent roles.

Uploads create Expert jobs. Validated resources are published; invalid citations and cyclic prerequisites stay unpublished for review. Starting/resuming a session invokes Tutoring. Submitting a response invokes Assessing, runtime validation, an evidence commit, then a handoff to Tutoring. The runtime owns answer keys, hints, evidence rules, versions and commits. Run events use the frontend v1 contract.

See `backend/README.md` for commands, endpoints, limits and tests. Local API uses port 8010; the worker runs separately. Credentials remain in ignored `backend/.env`.

Next phases:

1. Connect Materials, Learn, My understanding and Agent activity through a same-origin server proxy. Keep backend tokens private and replace demo state with authoritative APIs.
2. Add real account/membership authorization and staff review/repair before public deployment.
3. Improve larger-document coverage, cross-material concept merging, semantic activity diversity and evaluation against a manually reviewed course.
4. Add object storage, OCR, cancellation, job monitoring, budgets, backups and deployment configuration.

Automated citation/structure checks do not establish complete coverage or pedagogical correctness. Do not attach live runs to synthetic browser evidence.
