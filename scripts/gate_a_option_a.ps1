# Option A — ensure auxiliary tables on ep-old-resonance, then point Render at it
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host ""
Write-Host "Gate A Option A" -ForegroundColor Cyan
Write-Host "Creates note_links, auth_tokens, rate_limit_buckets on ep-old-resonance"
Write-Host "then you set Render DATABASE_URL to the same Neon URL."
Write-Host ""

$urlFile = Join-Path (Get-Location) ".gate_a_database_url"
if (-not $env:DATABASE_URL) {
    if (Test-Path $urlFile) {
        $env:DATABASE_URL = (Get-Content $urlFile -Raw).Trim()
        Write-Host "Loaded DATABASE_URL from .gate_a_database_url"
    } else {
        Write-Host "Paste your ep-old-resonance pooled connection string (one line):" -ForegroundColor Yellow
        $line = Read-Host "DATABASE_URL"
        if (-not $line) { Write-Error "DATABASE_URL required"; exit 1 }
        $env:DATABASE_URL = $line.Trim()
        Set-Content -Path $urlFile -Value $env:DATABASE_URL -NoNewline
        Write-Host "Saved to .gate_a_database_url (gitignored)"
    }
}

$env:FLASK_APP = "run:app"
python scripts\gate_a_option_a.py
exit $LASTEXITCODE
