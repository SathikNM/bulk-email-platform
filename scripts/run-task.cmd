@echo off
REM Runs logs\task.py inside the API container (one-off data maintenance). Output: logs\task.log
setlocal
cd /d "%~dp0.."
set LOG=logs\task.log
echo === task %date% %time% === > "%LOG%"
docker compose -f infra/docker-compose.yml --profile app exec -T api python - < logs\task.py >> "%LOG%" 2>&1
echo EXIT=%errorlevel% >> "%LOG%"
