@echo off
REM Phase 2 verification: start services, migrate, seed, run integration tests.
REM Runs inside a throwaway python:3.12 container; your source folder is mounted read-only.
REM Output: logs\phase2-verify.log
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set LOG=logs\phase2-verify.log
echo === Phase 2 verify %date% %time% === > "%LOG%"

echo [1/2] Starting services... >> "%LOG%"
docker compose -f infra/docker-compose.yml up -d --wait >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo [2/2] Migrate + seed + tests... >> "%LOG%"
docker run --rm --network bulk-email-platform_default ^
  -v "%cd%\backend:/src:ro" ^
  -e DATABASE_URL=postgresql+psycopg://bep:bep@postgres:5432/bep ^
  python:3.12-slim sh -c "cp -r /src /app && cd /app && pip install -q --root-user-action=ignore --disable-pip-version-check -r requirements-dev.txt && python -m alembic upgrade head && python -m app.db.seed && python -m pytest -q" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo RESULT=SUCCESS >> "%LOG%"
exit /b 0

:fail
echo RESULT=FAILED (exit %ERRORLEVEL%) >> "%LOG%"
exit /b 1
