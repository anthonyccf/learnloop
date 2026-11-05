# SQLite development setup

LearnLoop uses SQLite plus sqlite-vec by default. Application data, uploaded
document bytes, source passages and embedding vectors share `backend/data/learnloop.db`.
No Docker, PostgreSQL or Qdrant server is needed for this setup.

## First checkout (Windows)

For the complete first-run sequence and troubleshooting, start with the [root README](../../README.md#local-setup-for-teammates-sqlite). Install Python 3.12 and Node.js 20.9 or newer with npm, then run from the repository root:

```powershell
.\backend\scripts\development\setup.ps1
```

This creates a virtual environment, creates `.env` with a random backend token if
it does not already exist, installs pinned dependencies and applies Alembic
migrations. Existing `.env` files are preserved. Relative SQLite paths resolve
from `backend/`, including when commands are started from another directory.

Configure these in `backend/.env`:

- `DATABASE_URL=sqlite:///data/learnloop.db`
- `OLLAMA_BASE_URL` for an accessible Ollama service with `bge-m3` installed
- `OPENROUTER_API_KEY` for generation
- `API_TOKEN` and `LOCAL_OWNER_ID` for this local workspace

SQLite stores/searches embeddings; Ollama still generates them. The LLM is also
still required for real course preparation, coaching and assessment. Poppler is
optional for original PDF slide previews; extracted text remains the fallback.
For local embeddings, start Ollama and run `ollama pull bge-m3`. Keep
`OLLAMA_EMBEDDING_MODEL=bge-m3`, `OLLAMA_EMBEDDING_ENDPOINT=/api/embed` and
`EMBEDDING_DIMENSIONS=1024`. Use your own OpenRouter key and an accessible model.

From `backend/`, run these in separate terminals:

```powershell
.\.venv\Scripts\python -m uvicorn learnloop.main:app --host 127.0.0.1 --port 8010
```

```powershell
.\.venv\Scripts\python -m learnloop.worker
```

On first setup, copy `frontend/.env.example` to `frontend/.env.local`.
Configure `frontend/.env.local` using `LEARNLOOP_BACKEND_URL=http://127.0.0.1:8010`
and `LEARNLOOP_API_TOKEN` equal to the private backend token. From `frontend/`,
run `npm ci`, then `npm run dev`. Never expose this token through `NEXT_PUBLIC_*`.
Restart the API and worker after editing backend settings, and Next.js after
editing frontend settings. Open `http://127.0.0.1:3100/materials` to create your
first course and upload a document; a fresh database has no preloaded courses.

Each teammate owns their own local database. Share code, migrations and permitted
sample documents in GitHub. Do not commit `.env`, database files or live learner
records. For a common starting course, upload the same sample documents locally.

## Concurrency and vectors

WAL mode and a 30-second busy timeout are enabled. Write sessions reserve the
writer with `BEGIN IMMEDIATE` before reading state; foreign keys are enforced at
commit. UTC timestamp offsets are restored on ORM reads.

One SQLite worker executes jobs sequentially. A cross-process OS file lock next
to the database prevents another worker from executing jobs, including after a
lease expires while the original worker is still alive. A crash releases that
lock; expired job leases can then be recovered. Long preparation can delay
tutoring jobs, but model/embedding calls do not hold the main write transaction.

Embeddings are float32 blobs with model/dimension metadata. `sqlite-vec` computes
exact cosine distances, filtered by owner, course and allowed document IDs before
limiting results. SQL release/publication checks remain authoritative. This is an
exact scan suitable for class-project datasets, not an approximate vector index.
Changing embedding model/dimensions requires rebuilding the stored vectors.

## Checks and backups

From `backend/`:

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m ruff check learnloop scripts tests migrations
.\.venv\Scripts\python -m pip check
```

Tests create temporary SQLite databases with fake generation/embedding services;
vector tests also exercise the real sqlite-vec extension. No server or paid calls
are required. Real-service validation is opt-in and can make paid model calls.

Stop the API and worker before copying a live database, or use Python's SQLite
backup API. In WAL mode, copying only `.db` while services are writing may omit
changes still in the `-wal` file. Keep live databases on a local disk.

## Import an existing PostgreSQL/Qdrant workspace

Keep the original `.env` until import succeeds. Stop application writes and finish
or pause active jobs. Install the optional PostgreSQL driver:

```powershell
.\.venv\Scripts\python -m pip install -r requirements-migration.txt
.\.venv\Scripts\python -m scripts.development.migrate_sqlite data/learnloop.db
```

The destination must be new. Import reads a consistent PostgreSQL snapshot, copies
and fingerprints all application records, retrieves existing scoped Qdrant vectors
without re-embedding, checks SQLite integrity, and only then publishes the new
file. It never writes to the source services. A `.migration.json` report records
table/vector counts. Failed staging files remain available for diagnosis.

Back up `.env`, change only `DATABASE_URL` to the SQLite URL, then restart API and
worker. PostgreSQL/Qdrant remain intact for rollback; rollback will not include
new changes subsequently made in SQLite.

Legacy revision-0002 workspaces can be imported. Their session pins become null
and their release table starts empty. Current code requires complete validated
course releases: try the no-generation `POST /api/courses/{id}/releases` endpoint
first. Missing/stale curriculum or scope reviews require the normal preparation
workflow described in `course-releases.md`; import never bypasses these checks or
silently makes paid model calls.

If the imported courses already contain complete grounded lessons and curricula,
but lack the current content-bound scope receipts, run:

```powershell
.\.venv\Scripts\python -m scripts.development.validate_legacy_releases --apply
```

This backs up SQLite, reviews the existing scopes/lessons using the configured
model, saves resumable content-bound receipts, and publishes only when every
current gate passes. These review calls incur model usage. It preserves learner
history and does not regenerate lessons. A rejected lesson needs targeted repair
through the normal preparation workflow before its course can be published.
An empty map after importing saved materials can indicate an unpublished course;
restarting healthy services does not resolve missing publication validation.
