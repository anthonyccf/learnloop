# LearnLoop backend

FastAPI + SQLite/sqlite-vec + a separate durable worker. Uses local 1024-dimensional cosine vector search with `bge-m3` embeddings, and OpenRouter `openai/gpt-6-luna` for Expert, Tutoring and Assessing.

The three proposal agents have separate implementations and prompt files under [`learnloop/agents/`](learnloop/agents/). Start with the [agent architecture and class walkthrough](docs/agent-architecture.md) to follow responsibilities, tool use, shared runtime boundaries, and the current proposal gaps. The interface labels Tutoring as **Tutor** and Assessing as **Reviewer**.

For a new checkout, follow the [teammate setup in the root README](../README.md#local-setup-for-teammates-sqlite), including Ollama, OpenRouter and frontend configuration. See the [SQLite development and migration guide](docs/sqlite-development.md) for storage, backups and importing an existing workspace.

## Run locally (PowerShell)

From the project root, initialize the default SQLite database:

```powershell
.\backend\scripts\development\setup.ps1
```

Setup creates `.venv`, installs pinned dependencies, generates `backend/.env` with a random token if absent, and runs migrations. Existing `.env` files are preserved. Set `OPENROUTER_API_KEY` in `backend/.env`, keep `DATABASE_URL=sqlite:///data/learnloop.db`, and ensure Ollama has `bge-m3` installed. Then start the API:

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn learnloop.main:app --host 127.0.0.1 --port 8010
```

In another terminal, from the same folder:

```powershell
.\.venv\Scripts\python -m learnloop.worker
```

With SQLite the worker processes one job at a time. A cross-process file lock prevents duplicate execution, including when a job lease expires during a long model call. Write transactions use `BEGIN IMMEDIATE`; model calls stay outside them. `--workflow` filters jobs and `--once` processes at most one job. The legacy PostgreSQL adapter retains its three independent lanes and advisory locking.

API docs: <http://127.0.0.1:8010/docs>. Liveness: `/health/live`. Authenticated readiness: `/health/ready`. Port 8010 avoids existing services on ports 8000 and 8001. Startup does not automatically run migrations or prepare course content. Apply migrations explicitly; do not downgrade a database containing wanted records.

All `/api/*` and readiness requests require `Authorization: Bearer <API_TOKEN>` from the private `.env`. Swagger supports **Authorize**. No CORS or cookie access is enabled. This first version is a local, single-owner API: the server derives identity from `LOCAL_OWNER_ID`; clients cannot supply learner identity. Real accounts, membership and staff roles must precede public deployment.

## Working flow

Expert material preparation repairs rejected packs automatically with at most two revisions. Citation lookup corrects a near-miss ID only when its quote matches exactly one nearby ID in the uploaded document; every correction still requires independent source-support review. Repairs expand the document evidence search from six to twelve and then eighteen passages, send the rejected pack and review feedback to the model, and revise lessons and private tests together. Verified packs and learner progress are retained. Unsupported content stays withheld after exhausted repairs. Repair and citation lookup steps appear in Agent activity. Publication rechecks the reviewed source fingerprint against current document passages.

The Expert now reviews **every extracted passage**, grouped into contiguous sections of up to eight passages / roughly 10,000 characters. Each section identifies its distinct learning goals without a concept quota; non-teaching sections may contribute none. A separate semantic matching pass merges repeated goals while retaining distinct mechanisms, formulas, applications, and comparisons. The final graph has no fixed document-wide concept count cap. Section outputs and merge mappings are checkpointed; completed sections survive retries.

After section discovery, the Expert coordinates three sub-agent model calls with separate contexts: **Course Organizer** and **Relationship Analyst** run independently in parallel over the full published course catalog; **Relationship Reviewer** audits proposed dependencies against source passages and can remove or downgrade them to related links. The runtime coordinator checks exact topic coverage, unique/known concept IDs, evidence references, and an acyclic prerequisite graph before publishing atomically. Related links and topic membership never gate practice. Existing concept IDs, resources and evidence are retained. Topic/member order follows source teaching sequence, while prerequisites are ranked within topic groups on the map.

Related links are undirected. The coordinator removes reversed/exact duplicates and omits a related link when an accepted prerequisite already covers that pair. Unknown concepts, self-links, invalid sources and cycles still fail validation. A failed organization keeps up to three diagnostic drafts in the private run input and retries only the invalid topic/review stage. Grounding-rejected section and material drafts receive the review findings for at most two corrective regenerations; every revision must pass the same source checks. Exhausted or inconclusive evidence still stops for review, with private review diagnostics retained.

Expert generation uses short passage aliases in model prompts and maps them back to real passage IDs before saving. Concept IDs and source text are unchanged by this translation. Only known references can resolve; fingerprints and persisted citations use the real IDs.

`POST /api/courses/{id}/organize` upgrades an existing course without repeating section extraction or lesson/test generation. Duplicate requests reuse active preparation; an unchanged organized catalog returns `ready`. Checkpointed sub-agent outputs survive retries. Organization carries a catalog fingerprint: it is ignored when concepts change and rejected if the catalog changes during generation. The course API exposes `topics`, `related`, reviewed `prerequisites`, and organization coverage; no private tests are exposed. A complete map means all concepts belong to one topic each, not a forced fully connected graph or guaranteed pedagogical correctness.

To verify the real upgrade with preservation checks: `python -m scripts.validation.organized_course COURSE_ID --start`, then run without `--start` after the worker completes. The script records a baseline and reports full concept coverage, cycles, connected components, and hashes confirming unchanged learner evidence and lesson/test banks under `../tmp/`.

`POST /api/documents/{id}/analyze` upgrades a previously sampled upload to full-section review. It retains existing concept IDs, prerequisite relationships, lessons, private test banks, sessions, and learner evidence; newly discovered concepts receive new lessons and tests. Course document metadata reports processed/total passages, reviewed/total sections, and the resulting concept count. Coverage describes passages reviewed, not a guarantee of complete pedagogical correctness. Source IDs and a separate support review now gate newly prepared concepts and resources.

Expert preparation builds a course-wide learning pyramid before authoring lessons. Repeated goals across sections and uploads share one primary home. Reviewed prerequisite relationships drive basic foundations, intermediate applications and advanced integration. Each objective has a single exclusive teaching scope, its assumed prerequisites and the new capability it adds. An independent curriculum review and deterministic validation check complete coverage, distinct scopes, prerequisite direction, lower-layer connections and tapering layer counts. Counts guide classification; unsupported advanced goals are not invented.

Material version 4 authors one primary short lesson and worked example per objective, with source-supported formulas, takeaway, common mistake and flashcards. It retains two private multiple-choice questions at each assessment difficulty; curriculum layer, assessment difficulty and learner mastery target are separate. Source review checks factual support, and a separate teaching-scope review rejects substantial reteaching of other objectives. Brief prerequisite reminders and applying foundations in a new problem remain allowed. Accepted packs are checkpointed, while rejected packs stay withheld. Older lesson packs are regenerated against the assigned scope. New uploads also prepare any earlier lessons invalidated by a changed curriculum.

The Learn page displays a pyramid with layer counts and prerequisite lesson links. The concept reader shows the objective's primary lesson rather than a selector for three rewritten variants. `python -m scripts.development.rebuild_pyramid --apply` explicitly backs up and clears the local owner's generated graphs, retains uploaded files/passages and historical responses, ends old sessions, clears old plan data, and queues one complete rebuild per course using the configured OpenRouter provider. Without `--apply` it reports the reset scope only.

`python -m scripts.validation.pyramid` audits the local owner's saved curricula and materials without changing them. It checks layer counts, complete objective coverage, prerequisite paths, current material versions, source receipts, question-bank coverage and duplicate primary explanations, and writes `../tmp/pyramid-validation.json`. Earlier learning-post/difficulty validation scripts describe previous material versions.

`GET /api/courses/{id}/materials` returns lessons, slide references, and test counts, with no test answer keys. Only packs with current grounding receipts are returned and counted as ready. For older packs, `POST /api/documents/{id}/materials` reviews their saved content and preserves valid lessons/tests; unsupported or uncertain packs remain withheld and are flagged in document review. Review calls use the configured generation service and add model latency/cost; unchanged saved receipts avoid repeat reviews during preparation and assessment. Existing published documents can be upgraded with `POST /api/documents/{id}/materials`; repeated requests reuse a pending run. New uploads prepare both automatically. The Tutor assigns unused Expert questions first, then generates adaptive questions when that bank is exhausted. `/api/documents/{id}/review` also excludes private tests.

1. `POST /api/courses`, JSON `{ "title": "Training & optimization" }`.
2. `POST /api/courses/{id}/documents`, multipart field `file`, a readable PDF or UTF-8 `.txt`. Returns `documentId` and `runId`. The document and Expert job persist together. Identical content in the same course returns the original document/run.
3. The worker extracts page-aware passages, upserts deterministic chunk IDs, asks Expert for concepts/prerequisites, checks DAG structure and source support, and publishes accepted concepts. Unknown/empty citations and unsupported/inconclusive grounding reviews block the affected item with `needs_review`; inspect `/api/documents/{id}/review`. Faithful paraphrases are allowed. Lessons and private tests are separately reviewed before their packs are saved.
4. `GET /api/courses/{id}` returns published concepts, prerequisites and document status. `POST /api/courses/{id}/search`, JSON `{ "query": "...", "limit": 5 }`, retrieves published sources. Read `/api/documents/{id}/pages/{page}` for extracted passages.
5. `GET /api/courses/{id}/learner-state`, then `POST /api/courses/{id}/sessions`, JSON `{ "expectedLearnerVersion": 0 }`. An active session is resumed. Tutoring selects an eligible concept, retrieves sources and assigns a question at the selected difficulty. Get the question from `/api/sessions/{id}`.
6. Optional `POST /api/activities/{id}/hint` persists assisted usage before returning the hint. The client cannot erase or supply that usage in an answer.
7. `POST /api/activities/{id}/responses`, JSON `{ "operationId": "stable-uuid", "expectedLearnerVersion": 0, "choiceId": "a" }`. Save `submissionId` and `runId`. Identical retries return the same receipt; conflicting operation IDs, repeat submissions and stale versions return 409.
8. Assessing produces feedback/uncertainty. The server grades with its private key; runtime evidence rules, the assessment, versions and accepted events commit atomically. The answered question and its assessment remain current until the learner explicitly requests the next activity. Read feedback from `/api/submissions/{id}`, updated `/api/courses/{id}/learner-state`, and `/api/courses/{id}/assessments` history.
9. `POST /api/sessions/{id}/end` ends a session; submitted responses may still finish assessment. `POST /api/sessions/{id}/next` with the current `expectedLearnerVersion` requests another activity only after the learner chooses Next question; it retains a pending question and refuses to skip an unassessed response.

Discover runs with `GET /api/courses/{id}/runs`. Snapshot: `/api/agent-activity/runs/{id}`. SSE: `/api/agent-activity/runs/{id}/events?after_sequence=N`. Commands: `POST /api/agent-activity/runs/{id}/commands`, JSON `{ "kind": "retry", "operationId": "stable-uuid", "expectedVersion": 0 }`. Use only advertised allowedCommands. A separate worker must run, otherwise jobs remain queued. Agents wait while the learner thinks.

Run summaries include `startedAt`, `documentId`, and `sessionId` for contextual status in the learning UI. New runs store an internal creation timestamp in their input JSON; older summaries fall back to their first event timestamp. The public projection does not expose the remaining run inputs or private test data.

To practice a particular lesson, pass optional `conceptId` to `POST /api/courses/{id}/sessions`. The server validates course ownership, publication and prerequisites at each parent's target difficulty before changing anything. Unknown topics return 404; blocked prerequisites or a submitted answer awaiting assessment return 409 with a clear explanation. Focus is saved in the session's next-activity run inputs and exposed as `targetConceptId`. Explicit focused review may include an already demonstrated concept, but prerequisite checks still apply. Next question retains focus. Switching topics preserves pending activities, and switching back reuses an unanswered question. A stale tab cannot submit or request a hint for a non-current activity. No schema migration is needed, and existing general sessions remain adaptive.

## Structure and durability

Start with the [codebase layout and maintenance guide](docs/codebase-layout.md) for the folder tree, dependency boundaries, and commands.

| Folder | Responsibility |
| --- | --- |
| `learnloop/api/` | Application setup, shared ownership checks, and route groups for health, courses, documents, sessions, assessments, and agent activity. |
| `learnloop/agents/` | Expert, Tutoring, and Assessing implementations and their prompts. |
| `learnloop/core/` | Configuration, shared errors, structured contracts, and deterministic learning/evidence rules. |
| `learnloop/persistence/` | SQLAlchemy tables, connection factories, course/learner queries, and retrieval projections. |
| `learnloop/services/` | Model, embedding, vector-store clients, and PDF slide rendering. |
| `learnloop/runtime/` | Durable queue worker, workflow dispatch/recovery, validated events, and the public event schema. |
| `scripts/validation/` | Opt-in smoke, course organization, lesson, worked-example, and acceptance checks. |
| `scripts/development/` | Disposable API/worker sandbox for development journeys. |
| `scripts/contracts/` | Frontend-to-backend schema export tooling. |
| `tests/` | Tests grouped by API, agents, core rules, and services; shared fixtures stay in `conftest.py`. |
| `migrations/` | Explicit Alembic revisions and SQL schema history. |

`learnloop.main:app`, `learnloop.api.create_app`, and `python -m learnloop.worker` remain stable entry points. The worker implementation is in `runtime/worker.py`; `runtime/workflows.py` maps the three workflow IDs to their agent handlers. `runtime/events.py` validates snapshots/events against the adjacent `agent-contract.schema.json`. Model calls run outside database write locks, and checkpoints avoid duplicate assessment commits.

Two distinct independent correct activities establish demonstrated evidence only at their actual difficulty. Overall progress uses the concept's target (Intermediate by default). Hints do not qualify; incorrect or uncertain results reset qualifying evidence and prompt review of prior mastery. Expired review evidence needs new independent checks. Submission history is retained. Answer keys, hints and explanations are private; only assessed feedback exposes explanations.

SQLite is authoritative. Local vectors carry owner/course/document IDs; search filters all three and validates returned IDs against SQL ownership/publication. Partially indexed unpublished documents cannot enter learner retrieval. Vector upserts are idempotent; embedding requests happen before short local vector writes.

Quiz assignments first check lecture support. If that review finds unsupported or insufficient evidence, a separate Expert review may approve accurate additional knowledge that is important for understanding the selected concept. Approved questions carry an **Extended topics** badge and a learner-facing reason explaining the coverage gap. Their private receipt uses `status: extended`, binds approval to the exact question and related passages, and is reused during assessment; it does not claim lecture support. Incorrect, ambiguous, irrelevant or unverifiable questions and invalid citations still require review. This applies to quiz assignment, not publication of lecture-grounded course materials. The activity JSON stores the badge and approval without a schema migration.

## Configuration

Slide previews render original PDF pages with Poppler's `pdftoppm`. Optionally install Poppler and add it to PATH, or set the process environment variable `PDFTOPPM_PATH` to the executable before starting the API (PowerShell: `$env:PDFTOPPM_PATH = 'C:\path\to\pdftoppm.exe'`). This renderer reads the process environment directly; putting this setting only in `.env` does not configure it. The authenticated `/api/documents/{id}/pages/{page}/slide` endpoint returns a PNG of the requested page. Page bounds and document ownership are checked before rendering. If rendering is unavailable, the frontend retains extracted text as a fallback. Text uploads use the text view directly.

The loader resolves `backend/.env` independently of the current folder. `.env` is ignored; `.env.example` has no credentials. Supply your own OpenRouter key. Never expose credentials using `NEXT_PUBLIC_*` variables. Restart the API and worker after changing configuration; exported environment variables override `.env` values.

Settings: `DATABASE_URL` (defaults to `sqlite:///data/learnloop.db`), `API_TOKEN`, `LOCAL_OWNER_ID`, `OLLAMA_BASE_URL`, `OLLAMA_EMBEDDING_MODEL`, `OLLAMA_EMBEDDING_ENDPOINT`, `EMBEDDING_DIMENSIONS`, `OPENROUTER_BASE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `EXPERT_MATERIAL_WORKERS`. Qdrant settings are only used by the optional legacy PostgreSQL adapter/import tool. Relative SQLite paths resolve from `backend/`.

Default limits: 20 MiB files, 200 PDF pages, 1000 chunks, 90-second service calls, three attempts. Expert reviews all extracted passages in checkpointed sections, merges repeated goals, and reports full passage coverage; there is no fixed document-wide concept quota. Missing generation credentials pause runs; configure and restart services, then resume. Readiness checks generation configuration, not paid inference.

## Tests

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pip check
# Real services and paid model calls, using synthetic material:
.\.venv\Scripts\python -m scripts.validation.smoke --live
```

Integration tests now run by default in temporary SQLite files with fake model/embedding services. Local vector tests use the real sqlite-vec extension. Live smoke creates a disposable SQLite file; its records and vectors are isolated from the working database.

The broader real-service acceptance journey checks a multi-topic upload, complete lessons/map, wrong and hinted responses, two independent checks, explicit Next, history, and continued practice. See [learning journey validation](docs/learning-journey-validation.md) for the results, limits and repeatable sandbox commands.

The schema-export source is `frontend/src/lib/agent-activity/contracts.ts`; `scripts/contracts/export.ps1` regenerates its JSON Schema projection. `requirements.lock.txt` pins the complete tested environment, including test dependencies.

## Integration and remaining work

The Next.js frontend is connected through its private same-origin backend proxy. Uploads, lessons, practice, evidence, and activity history use saved backend data. Frontend public event contracts/adapters live in `frontend/src/lib/agent-activity/`; they display execution performed by the Python agents and do not implement those agents. See the [frontend README](../frontend/README.md).

Goal-aware planning and rubric assessment with optional written reasoning are implemented. LangGraph and general essay activities remain pending. The controlled evaluation harness is implemented; human review and research execution remain pending. The [implementation-status table](docs/agent-architecture.md#proposal-versus-current-implementation) separates current functionality from planned research work.

Not implemented: multi-user login, staff approval/repair, OCR/image extraction, cross-document concept merging, object storage, cancellation, semantic question deduplication, guaranteed full document coverage, usage/cost accounting and production deployment hardening. Review-required output cannot yet be approved through the API. This is a runnable local backend slice.

## Difficulty-aware learning

See [difficulty adaptation and validation](docs/difficulty-adaptation-validation.md). Use a conceptâ€™s Goals tab to set its Learning target and its Learning material tab to select a lesson level. Older packs keep their original lesson and questions; Prepare all lesson levels adds missing resources through the existing material workflow. Practice can also generate a missing level on demand. Source validation remains mandatory. No migration or course reset is required.

## Tutor goals and rubric assessment

The Tutor now ranks prerequisite-safe educational actions using need, uncertainty, review urgency, recent performance and the saved learning goal. A bounded model choice and rationale are saved with versioned plans and immutable revisions. The Tutor page exposes a learning-goal editor.

New Expert questions include source-backed private reference answers and weighted rubrics. Assessment records criterion coverage, optional written reasoning, grounded misconception quotes, contradictions, prior assessment references and server elapsed response time. Partial/uncertain/assisted responses cannot establish demonstration. Existing activities remain usable through reviewed rubric upgrades.

Apply `python -m alembic upgrade head` (current head: `0004`, including local vector storage) before restarting the updated API and worker. The goal/rubric migration adds three tables and preserves existing content/progress. See [planning and assessment validation](docs/planning-assessment-validation.md) for APIs, checks and remaining limits.


Assessment evidence and mastery targets follow the published curriculum layer: Basic uses Basic, Intermediate uses Intermediate, and Advanced uses Advanced. The map no longer has a separate evidence-difficulty selector. Assigned concepts have a fixed, matching target; unassigned legacy concepts retain their saved target (Intermediate fallback). Existing evidence remains at its original difficulty, including pending activities, and is never relabelled or deleted. Older catalog targets are resolved at read time, preserving source/resource signatures and learner versions. Practice may still adapt down for support, while mastery and prerequisite readiness require evidence at the curriculum layer.

## Controlled evaluation

The [evaluation harness](docs/evaluation-harness.md) implements the 27 prompt combinations, four hidden learner profiles, frozen resources, independent pre/post scoring, repeated episodes and matched baselines. A 12-concept COMP7608B draft and model-screened resources are prepared. Research execution requires recorded human review; offline checks and live canaries are not learning-effectiveness results.

## Complete course releases

Proposal gap 9 is implemented. Expert preparation publishes a version only after graph, curriculum, lessons and all three quiz levels validate. Sessions retain their release while later uploads prepare; failed preparation preserves the prior ready content. Release APIs return metadata and public lessons, keeping quiz keys private.

Apply migration `0003` and complete first-release validation for existing courses before switching services to this code. The migration preserves records and leaves legacy sessions unpinned until their next learning action. See [course release rollout and validation](docs/course-releases.md). This implementation task did not migrate or restart production services.
