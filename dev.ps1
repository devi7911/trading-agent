<#
  Convenience wrapper. Usage:  .\dev.ps1 <command>
#>
param([Parameter(Position = 0)][string]$Command = "help")

$ErrorActionPreference = "Stop"

switch ($Command) {
  "init" {
    if (-not (Test-Path .env)) {
      Copy-Item .env.example .env
      $key = python -c "import secrets; print(secrets.token_urlsafe(48))"
      (Get-Content .env) -replace '^SECRET_KEY=.*', "SECRET_KEY=$key" | Set-Content .env
      Write-Host "Created .env with a generated SECRET_KEY." -ForegroundColor Green
    } else {
      Write-Host ".env already exists - leaving it alone." -ForegroundColor Yellow
    }
  }
  "up"      { docker compose up --build }
  "down"    { docker compose down }
  "reset"   { docker compose down -v; docker compose up --build }
  "logs"    { docker compose logs -f api }
  "test"    { docker compose exec api pytest -v }
  "lint"    { docker compose exec api ruff check . }
  "migrate" { docker compose exec api alembic upgrade head }
  "shell"   { docker compose exec api bash }
  "psql"    { docker compose exec db psql -U trader -d trading }
  default {
    Write-Host @"
Commands:
  init      create .env from the example and generate a SECRET_KEY
  up        build and start everything
  down      stop everything
  reset     stop, wipe volumes, rebuild
  logs      follow the API logs
  test      run the test suite inside the api container
  lint      run ruff
  migrate   apply migrations
  shell     bash inside the api container
  psql      psql inside the db container
"@
  }
}
