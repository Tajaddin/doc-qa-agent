#requires -Version 5.1
<#
One-command setup for the doc-qa-agent project on Windows PowerShell.

Usage:
    powershell -ExecutionPolicy Bypass -File setup.ps1

Skips steps that are already done. Pauses and prompts for .env values when
required keys are missing.
#>

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

# 1. Python venv
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Step "Creating virtual env at .venv"
    python -m venv .venv
} else {
    Write-Step "Reusing existing .venv"
}

$Py = ".\.venv\Scripts\python.exe"

# 2. Dependencies
Write-Step "Installing project (editable) + dev extras"
& $Py -m pip install --upgrade pip --quiet
& $Py -m pip install -e .[dev] --quiet
Write-Ok "deps installed"

# 3. .env scaffold
if (-not (Test-Path ".env")) {
    Write-Step "Creating .env from .env.example"
    Copy-Item ".env.example" ".env"
    Write-Warn "Edit .env now and fill in:"
    Write-Warn "  ANTHROPIC_API_KEY"
    Write-Warn "  VOYAGE_API_KEY (or OPENAI_API_KEY)"
    Write-Warn "  DATABASE_URL  (Supabase or local pgvector)"
    Write-Warn "Then re-run setup.ps1."
    exit 0
}

# 4. Quick env sanity check
$envContent = Get-Content ".env" -Raw
if ($envContent -notmatch "ANTHROPIC_API_KEY=\S+") {
    Write-Warn "ANTHROPIC_API_KEY is empty in .env. Fill it before continuing."
    exit 1
}
if ($envContent -notmatch "DATABASE_URL=postgresql://\S+") {
    Write-Warn "DATABASE_URL looks unset in .env. Fill it before continuing."
    exit 1
}
Write-Ok ".env looks populated"

# 5. Migrations
Write-Step "Applying SQL migrations"
& $Py -m scripts.init_db

# 6. Smoke test
Write-Step "Schema smoke test"
& $Py -m scripts.test_db

# 7. Optional: ingest + embed
Write-Step "Optional next steps"
Write-Host "    Ingest the 80-page corpus: $Py -m doc_qa.ingest --limit 80"
Write-Host "    Embed every chunk:         $Py -m doc_qa.embeddings"
Write-Host "    Run the eval harness:      $Py -m eval.run_eval"
Write-Host "    Start the API:             $Py -m uvicorn doc_qa.api:app --host 127.0.0.1 --port 8000"
Write-Host "    Start the MCP server:      $Py -m doc_qa.mcp_server"
Write-Host ""
Write-Ok "setup complete"
