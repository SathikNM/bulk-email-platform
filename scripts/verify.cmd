@echo off
REM Full backend verification: start infrastructure, migrate, seed, run all integration tests.
REM Runs inside a throwaway python:3.12 container; your source folder is mounted read-only.
REM Output: logs\verify.log
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set LOG=logs\verify.log
echo === Verify %date% %time% === > "%LOG%"

echo [1/2] Starting infrastructure... >> "%LOG%"
docker compose -f infra/docker-compose.yml up -d --wait postgres redis mailpit >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo [2/2] Migrate + seed + tests... >> "%LOG%"
docker run --rm --network bulk-email-platform_default ^
  -v "%cd%\backend:/src:ro" ^
  -e DATABASE_URL=postgresql+psycopg://bep:bep@postgres:5432/bep ^
  -e REDIS_URL=redis://redis:6379/0 ^
  python:3.12-slim sh -c "cp -r /src /app && cd /app && pip install -q --root-user-action=ignore --disable-pip-version-check -r requirements-dev.txt && python -m alembic upgrade head && python -m alembic check && python -m app.db.seed && python -m pytest -q -p no:cacheprovider" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo RESULT=SUCCESS >> "%LOG%"
exit /b 0

:fail
echo RESULT=FAILED (exit %ERRORLEVEL%) >> "%LOG%"
exit /b 1
