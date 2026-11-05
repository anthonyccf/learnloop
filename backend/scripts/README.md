# Backend operational commands

- `validation/`: report-producing checks for smoke, learning journeys, course organization, posts, and examples.
- `development/`: disposable API/worker sandbox used by the learning journey.
- `contracts/`: export the frontend public event schema for backend validation.
- `paths.py`: shared backend/project/artifact paths; commands write reports to the project `tmp/` folder.

Run Python tools as modules from `backend/`, for example:

```powershell
.\.venv\Scripts\python -m scripts.validation.organized_course COURSE_ID
.\.venv\Scripts\python -m scripts.validation.learning_posts DOCUMENT_ID
.\.venv\Scripts\python -m scripts.validation.worked_examples DOCUMENT_ID
.\scripts\contracts\export.ps1
```

Use `--help` for options. The complete command list and module responsibilities are in the [backend maintenance guide](../docs/codebase-layout.md).
