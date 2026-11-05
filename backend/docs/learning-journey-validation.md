# Learning journey acceptance check

Validated on 19 October 2026 against the configured real model, embedding service,
PostgreSQL and Qdrant. Synthetic gradient descent notes were uploaded through the
HTTP API to a separate `ll_smoke_*` database schema. The normal durable worker
processed the upload and learning activities. The sandbox and its own vectors
were removed after validation.

## Results

| Acceptance condition | Result |
| --- | --- |
| Save upload and process it in the background | Passed |
| Review every extracted passage | Passed |
| Generate a complete organized concept graph | 3 concepts, 1 topic, 2 prerequisite links |
| Prepare lessons, structured worked examples, flashcards and private questions | 3 lessons, 6 prepared questions |
| Keep answer keys private before submission | Passed |
| Reuse a duplicate upload and completed preparation | Passed |
| Retrieve source passages using real embeddings and vector search | Passed |
| Explain prerequisite blockers for focused practice | Passed |
| Keep questions on the chosen lesson | Passed across four questions |
| Retain the answered question and analysis until explicit Next | Passed after every answer and repeated reads |
| Duplicate answer requests do not duplicate evidence | Passed |
| Incorrect answer records developing understanding | Passed |
| Hinted correct answer remains assisted evidence | Passed |
| Two independent correct answers demonstrate understanding | Passed; learner version 4, four attempts, two independent checks |
| Continue with new questions after the Expert's prepared pair | Passed using real Tutor generation |
| Save assessment history and retain it across sessions | Passed |
| Select the next eligible concept in a new session | Passed |
| Render the generated graph without overlapping cards | Passed: all 3 nodes and 2 edges |
| Render actual generated worked-example equations | Passed: 39 formula lines |
| Preserve original course graphs and learner history | Passed by before/after comparison |

An existing-course check found 48 of 51 lesson positions differed from the
Expert's organized map/tutor order. The materials endpoint now projects lessons
in the same published concept sequence, including partially generated courses.
No stored lesson, graph or evidence is rewritten. Regression tests cover both
complete and partial generation. All 51 existing lessons now match that sequence.

Automated checks: **51 backend tests and 29 frontend tests pass**, with frontend
lint, TypeScript checks and production build passing. There is one existing
Starlette/AnyIO deprecation warning in backend tests.

## Scope and limits

This is a real API/worker acceptance journey through one small, multi-topic
module, supplemented by rendering checks and inspection of the existing frontend.
It does not establish subject-matter correctness for every generated lesson or
simulate studying all 51 concepts. The synthetic upload was text; PDF slide
orientation and source access have separate automated integration coverage.

A separate frontend server was blocked by automatic approval review, which
returned only “blocked by policy.” Consequently, a complete browser-only journey
against the disposable course was not verified. The existing frontend was
inspected to confirm the corrected lesson sequence.

## Repeat the checks

From `E:\agentic-learning\backend`, start the isolated API and worker:

```powershell
.\.venv\Scripts\python -m scripts.development.journey_sandbox
```

In another terminal in that directory:

```powershell
.\.venv\Scripts\python -m scripts.validation.learning_journey
```

From `E:\agentic-learning\frontend`, validate the actual generated graph and math:

```powershell
npx tsx scripts/check-learning-journey.ts
```

Reports are saved in `tmp/journey-report.json` and
`tmp/journey-frontend-report.json`. When all checks finish, shut down the sandbox
and remove only its temporary records and vector IDs:

```powershell
New-Item -ItemType File -Path E:\agentic-learning\tmp\journey-stop -Force
```

Wait for “Isolated journey schema and scoped vectors cleaned up.” The regular
API on 8010 and frontend on 3100 remain available throughout.
