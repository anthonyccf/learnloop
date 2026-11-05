$ErrorActionPreference = 'Stop'
$frontendRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../frontend'))
Push-Location $frontendRoot
try {
    & ./node_modules/.bin/tsx.cmd -e "import {z} from 'zod'; import {agentRunSchema,agentEventSchema} from './src/lib/agent-activity/contracts'; import {writeFileSync} from 'node:fs'; writeFileSync('../backend/learnloop/runtime/agent-contract.schema.json',JSON.stringify({snapshot:z.toJSONSchema(agentRunSchema),event:z.toJSONSchema(agentEventSchema)},null,2));"
    if ($LASTEXITCODE -ne 0) { throw 'Contract schema export failed.' }
} finally {
    Pop-Location
}
