# Backend layout and maintenance

Current local setup uses SQLite and sqlite-vec; see [SQLite development](sqlite-development.md). Jobs run sequentially with an OS file lock, and write sessions use `BEGIN IMMEDIATE`. PostgreSQL-specific commands and older validation results below describe the legacy adapter/history. Ordinary integration tests now run in temporary SQLite files without opt-in.


Run backend commands from `E:\agentic-learning\backend`. The API and worker use the same application packages; operational commands live under `scripts/`.

```text
backend/
  learnloop/
    main.py                   # API entry: learnloop.main:app
    worker.py                 # CLI entry: python -m learnloop.worker
    api/
      __init__.py             # Public create_app export
      app.py                  # App setup, middleware, errors, route registration
      dependencies.py         # Per-app services, ownership, session projections
      routes/
        health.py
        courses.py
        documents.py
        sessions.py           # Session lifecycle and tutor chat
        assessments.py        # Hints, answer submission, feedback, history
        activity.py           # Run listings, commands, and event streaming
    agents/
      expert/                 # Preparation, organization, teaching resources
      tutoring/               # Question assignment and conversational coaching
      assessing/              # Review and evidence commits
      references.py
    core/
      config.py               # Settings; resolves backend/.env
      domain.py               # Evidence, prerequisites, extraction rules
      errors.py               # Shared failure contract
      schemas.py              # Request and structured generation contracts
    persistence/
      database.py             # SQLAlchemy tables and session/engine factories
      repository.py           # Course, evidence, and retrieval queries
    services/
      clients.py              # Model, embedding, and Qdrant clients
      slides.py               # PDF rendering
    runtime/
      events.py               # Event/snapshot validation and persistence
      workflows.py            # Agent dispatch and failure recovery
      worker.py               # Queue claims, leases, retries, worker loop
      agent-contract.schema.json
  scripts/
    paths.py                  # Shared project/backend/artifact paths
    validation/               # Checks that produce reports
    development/              # Disposable local development services
    contracts/                # Public schema export
  tests/
    conftest.py               # Shared fixtures and model/vector test doubles
    api/                      # HTTP lifecycle, focused practice, tutor chat
    agents/                   # Expert analysis, lessons, organization
    core/                     # Learning/evidence rules
    services/                 # Provider transport contracts
  migrations/                 # Alembic history and initial SQL
  docs/
```

## Where to make a change

| Task | Start here |
| --- | --- |
| Add or change an HTTP endpoint | Matching `api/routes/` module; register a new group in `api/app.py` if needed. |
| Change authentication or ownership | `api/dependencies.py`; route groups use the same per-app `ApiContext`. |
| Change a learning policy | `core/domain.py` and `tests/core/`. |
| Add a structured request or model output | `core/schemas.py`; update the owning agent or route. |
| Change a table | `persistence/database.py` plus a new explicit Alembic migration. |
| Change a query or retrieval projection | `persistence/repository.py`. |
| Change a provider request | `services/clients.py` and `tests/services/`. |
| Change teaching, coaching, or feedback | The responsible `agents/` package and its prompt file. |
| Change job execution or recovery | `runtime/worker.py` or `runtime/workflows.py`. |
| Change public agent events | Frontend contracts, `runtime/events.py`, and the schema export command below. |
| Add a verification command | `scripts/validation/`; take report locations from `scripts.paths.ARTIFACT_ROOT`. |
| Add a disposable development service | `scripts/development/`. |

Keep learning policy independent of HTTP handlers and provider clients. Agents coordinate teaching work; the runtime owns durable jobs and public events. Route groups receive their context through `build_router(context)` so tests can inject isolated settings, database sessions, and service doubles. Public projections must continue to exclude private answer keys.

## Commands

Use the virtual environment's Python executable (`.\.venv\Scripts\python`) for the Python examples below.

| Purpose | Command |
| --- | --- |
| Start API | `python -m uvicorn learnloop.main:app --host 127.0.0.1 --port 8010` |
| Start worker | `python -m learnloop.worker` |
| Process one queued job | `python -m learnloop.worker --once` |
| Run ordinary tests | `python -m pytest -q` |
| Run database integration tests | Set `$env:LEARNLOOP_INTEGRATION_TESTS = "1"`, then run `python -m pytest -q`. |
| Lint | `python -m ruff check learnloop scripts tests migrations` |
| Check formatting | `python -m ruff format --check learnloop scripts tests migrations` |
| Export public event schema | `.\scripts\contracts\export.ps1` |
| Live service smoke check | `python -m scripts.validation.smoke --live` |
| Start isolated journey service | `python -m scripts.development.journey_sandbox` |
| Check the isolated journey | `python -m scripts.validation.learning_journey` |
| Verify course organization | `python -m scripts.validation.organized_course COURSE_ID` |
| Verify learning posts | `python -m scripts.validation.learning_posts DOCUMENT_ID` |
| Verify worked examples | `python -m scripts.validation.worked_examples DOCUMENT_ID` |

The last three commands accept `--start` to save a baseline and request the relevant upgrade. Their default mode checks progress and preservation. Live smoke and journey checks use real external services and may make paid model calls; ordinary tests use test doubles. See [learning journey validation](learning-journey-validation.md) for sandbox cleanup.

Report files remain under the project's `tmp/` directory. Script nesting does not change that location. Settings continue to resolve `backend/.env` independently of the working directory. Exported event JSON stays beside `runtime/events.py`.

`learnloop.main:app`, `learnloop.api.create_app`, and `learnloop.worker` remain stable. Internal imports use the grouped package paths above; older flat imports such as `learnloop.db` should be updated to `learnloop.persistence.database`.
