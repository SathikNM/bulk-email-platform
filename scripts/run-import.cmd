@echo off
REM Imports logs\import\import.xlsx into the platform (contacts). Output: logs\import.log
setlocal
cd /d "%~dp0.."
set LOG=logs\import.log
echo === import %date% %time% === > "%LOG%"
docker compose -f infra/docker-compose.yml --profile app cp logs\import\import.xlsx api:/tmp/import.xlsx >> "%LOG%" 2>&1
docker compose -f infra/docker-compose.yml --profile app exec -T api python - < scripts\run_import.py >> "%LOG%" 2>&1
echo EXIT=%errorlevel% >> "%LOG%"
