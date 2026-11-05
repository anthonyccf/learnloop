# LearnLoop Python agent lab

Run and tune **Expert**, **Tutoring** and **Assessing** from Python or the terminal,
without Node.js, a frontend, or a running API server. The lab imports the real
agents and workflow rules from the sibling `backend/`; keep both folders in the
same checkout. It has its own SQLite database and configuration.

Here, tuning means editing prompts, selecting models and changing Python agent
logic. This folder does not train model weights or submit fine-tuning jobs.

## First setup (PowerShell)

Install Python 3.12. From the repository root:

```powershell
cd agent_lab
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m learnloop_cli init
```

`init` creates a missing `.env`, exports missing prompt templates, and runs the
backend's Alembic migrations against `agent_lab/data/workspace.db`. Existing
configuration, prompt edits and database records are preserved. No model calls
are made during initialization.

Edit **`agent_lab/.env`**, not `backend/.env`:

| Setting | Default / action |
| --- | --- |
| `DATABASE_URL` | `sqlite:///data/workspace.db`; relative to the lab workspace. |
| `OPENROUTER_API_KEY` | Supply your own key. |
| `OPENROUTER_MODEL` | `openai/gpt-6-luna`; select a model your account can access. |
| `OLLAMA_BASE_URL` | `http://localhost:11434`, or your reachable Ollama server. |
| `OLLAMA_EMBEDDING_MODEL` | `bge-m3`. |
| `OLLAMA_EMBEDDING_ENDPOINT` | `/api/embed`. |
| `EMBEDDING_DIMENSIONS` | `1024` for `bge-m3`. |
| `REQUEST_TIMEOUT_SECONDS` | `90`; production generation uses longer timeouts for some large outputs. |

Start Ollama and run `ollama pull bge-m3` for full document workflows. SQLite and
sqlite-vec are installed by pip; no PostgreSQL, Qdrant server or Docker is needed.
The CLI generates its internal bearer token in memory; no token copying is needed.
It invokes the existing application routes in process and never opens a server port.

All commands below run from `agent_lab/`. You can activate the virtual environment
or keep using its explicit Python executable:

```powershell
.\.venv\Scripts\python -m learnloop_cli config
.\.venv\Scripts\python -m learnloop_cli doctor
.\.venv\Scripts\python -m learnloop_cli --help
```

`doctor` checks the database, sqlite-vec and a real embedding request. It checks
generation configuration, not a paid OpenRouter request or model availability.
It exits with an error if readiness is degraded. Exported shell variables override
`.env` values. The lab never reads `backend/.env`; database paths inside `backend/`
are rejected to prevent accidental changes to the web workspace.

## Tune the agents

Edit the versioned text files under **`prompts/`**:

| Agent | Useful starting templates |
| --- | --- |
| Expert | `expert/section_prompt.txt` (concept extraction), `expert/curriculum_prompt.txt` (curriculum), `expert/pyramid_materials_prompt.txt` (lessons/questions). |
| Tutoring | `tutoring/plan_prompt.txt` (action choice), `tutoring/question_prompt.txt` (new questions), `tutoring_chat/chat_prompt.txt` (conversation). |
| Assessing | `assessing/feedback_prompt.txt` (feedback and rubric coverage). |
| Shared reviews | `shared_grounding/grounding_prompt.txt`, `expert_rubric/rubric_prompt.txt`, `expert_extension/extension_prompt.txt`. |

List all template IDs with `python -m learnloop_cli prompts list`. Overrides are
read for every generation call. Templates are composed final instructions;
editing a material template does not rewrite other templates. Runtime suffixes
for independent reviews and cross-document deduplication are retained.
`prompts export` creates only missing files. To adopt a newer backend template,
first preserve your edits, remove that template, then export it again.

Select models independently in **`agents.toml`**:

```toml
[expert]
model = ""  # Empty means inherit OPENROUTER_MODEL.
[tutoring]
model = ""
[assessing]
model = ""
```

Each section accepts an OpenRouter model ID. Prompt/model changes here affect
the lab only. They do not replace the backend's prompts or configuration. Source
grounding, output schemas, private grading keys and evidence transitions still
use the production validators. A changed prompt does not bypass those checks.

For algorithm changes, the actual implementations are
[`expert/agent.py`](../backend/learnloop/agents/expert/agent.py),
[`tutoring/agent.py`](../backend/learnloop/agents/tutoring/agent.py), and
[`assessing/agent.py`](../backend/learnloop/agents/assessing/agent.py). Changes to
these shared Python files affect both the lab and the web app. Use a Git branch
for experiments you intend to compare or merge.

## Run the full three-agent workflow

Commands print JSON. Replace `COURSE_ID`, `SESSION_ID` and `RUN_ID` below with the
IDs returned by earlier commands. Upload/start/answer commands **queue work**;
`work` executes it in the same terminal and can make paid model calls.

```powershell
# Create a course; copy its returned id.
.\.venv\Scripts\python -m learnloop_cli courses create "Gradient descent"

# Expert: upload, execute preparation, inspect the resulting run/course.
.\.venv\Scripts\python -m learnloop_cli expert COURSE_ID examples/course.txt
.\.venv\Scripts\python -m learnloop_cli work --agent expert
.\.venv\Scripts\python -m learnloop_cli runs COURSE_ID
.\.venv\Scripts\python -m learnloop_cli courses show COURSE_ID

# Tutoring: start/resume a session; copy its id, then prepare its question.
.\.venv\Scripts\python -m learnloop_cli tutor COURSE_ID
.\.venv\Scripts\python -m learnloop_cli work --agent tutoring
.\.venv\Scripts\python -m learnloop_cli session SESSION_ID

# Assessing: submit one of the displayed choices, then inspect feedback.
.\.venv\Scripts\python -m learnloop_cli answer SESSION_ID a --reasoning "My explanation"
.\.venv\Scripts\python -m learnloop_cli work --agent assessing
.\.venv\Scripts\python -m learnloop_cli session SESSION_ID

# Advance explicitly after reviewing the assessment.
.\.venv\Scripts\python -m learnloop_cli next SESSION_ID
.\.venv\Scripts\python -m learnloop_cli work --agent tutoring
```

Use `tutor COURSE_ID --concept-id CONCEPT_ID` to focus a published, eligible
lesson. `end SESSION_ID` ends a session. `work --max-jobs 5` processes at most
five queued jobs; the default is one. A processed job can be paused, failed or
awaiting review, so inspect `runs COURSE_ID` or `run RUN_ID` for its outcome.
Successful assessment uses `waiting_for_learner` while you read the feedback.

For paused runs, fix configuration, then `resume RUN_ID`. For retryable failures,
use `resume RUN_ID --kind retry` when the run advertises that command. Backend
attempt limits still apply. Ctrl+C preserves saved jobs/checkpoints; an interrupted
running job may need its lease to expire before recovery.

Saved lessons, question banks and completed checkpoints are reused. Changing a
prompt does not regenerate earlier work automatically. Use a new course or a new
workspace for a clean comparison; uploading an identical file to the same course
returns its original job.

## Test a single prompt quickly

This makes one real model call without creating a course, generating embeddings,
or running a worker. It needs an OpenRouter key, but not Ollama:

```powershell
.\.venv\Scripts\python -m learnloop_cli call tutoring --prompt tutoring_chat/chat_prompt --schema TutorChatReply --context examples/tutor-context.json
```

Use any prompt ID from `prompts list` with its matching Pydantic schema from
[`core/schemas.py`](../backend/learnloop/core/schemas.py). For example, Expert's
`section_prompt` uses `SectionGraph`, Tutoring's `plan_prompt` uses `PlanChoice`,
and Assessing's `feedback_prompt` uses `Assessment`. Supply the context fields
required by that prompt. Schema validation checks structure; a single-call
experiment does not perform the full workflow's grounding/publication checks
and does not change learner evidence.

Every generation call records its role, model, effective instruction, prompt hash,
input context, validated output (or sanitized error), and duration in
**`data/traces/*.json`**. Parallel calls get separate trace files. These are private
local debugging artifacts that may contain source text and answer keys; `data/`
is ignored by Git. Commit prompt edits and synthetic fixtures for reproducibility.

## Use directly from Python

From `agent_lab/`, or from a script in that folder:

```python
from learnloop_cli import Workspace
from learnloop.core.schemas import TutorChatReply

with Workspace() as lab:
    lab.initialize()
    course = lab.create_course("My experiment")
    # lab.upload(course["id"], "examples/course.txt")
    # lab.work("expert")
    reply = lab.call("Tutoring", "tutoring_chat/chat_prompt", {
        "assessment_pending": False,
        "messages": [{"role": "user", "text": "Explain the supplied lesson."}],
        "lesson": "A learning rate controls the update step size.",
    }, TutorChatReply)
    print(reply.text)
```

For isolated variants, use `python -m learnloop_cli --workspace experiments/variant-a init`,
edit that directory's `.env`, `agents.toml` and prompt files, and pass the same
`--workspace` on subsequent commands. In Python, use
`Workspace("experiments/variant-a")`. Each variant has a separate database and traces.

## Offline checks

From `agent_lab/`:

```powershell
.\.venv\Scripts\python -m pytest tests -q
.\.venv\Scripts\python -m ruff check learnloop_cli tests
```

Tests use temporary SQLite databases and the backend's fake model/embedding
responses. They verify the complete three-agent workflow, configuration isolation,
prompt overrides, model selection and traces without paid calls or external servers.
