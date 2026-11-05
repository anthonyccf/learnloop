$ErrorActionPreference = 'Stop'
$backendRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $backendRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    if (-not (Test-Path -LiteralPath '.env')) {
        @'
from pathlib import Path
import secrets
p = Path('.env.example').read_text()
p = p.replace('REPLACE_WITH_A_RANDOM_LOCAL_BACKEND_TOKEN', secrets.token_urlsafe(32))
Path('.env').write_text(p)
'@ | & .\.venv\Scripts\python -
        if ($LASTEXITCODE -ne 0) { throw 'Environment configuration failed.' }
    }
    & .\.venv\Scripts\python -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & .\.venv\Scripts\python -c "from learnloop.core.config import get_settings; assert get_settings().uses_sqlite, 'Use the migration guide before replacing an existing PostgreSQL workspace.'"
    if ($LASTEXITCODE -ne 0) { throw 'Expected SQLite configuration; existing data was not changed.' }
    & .\.venv\Scripts\python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
    Write-Output 'SQLite is ready. Configure the embedding/model services in backend/.env, then start the API and worker.'
} finally {
    Pop-Location
}
