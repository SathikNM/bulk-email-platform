@echo off
REM Build and start the whole platform in Docker: database, Redis, Mailpit, API, workers, scheduler, web.
REM First run builds the images (5-10 minutes). Output: logs\start-platform.log
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set LOG=logs\start-platform.log
echo === Start platform %date% %time% === > "%LOG%"
docker compose -f infra/docker-compose.yml --profile app up -d --build --wait >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
echo --- service status --- >> "%LOG%"
docker compose -f infra/docker-compose.yml --profile app ps >> "%LOG%" 2>&1
echo --- API readiness --- >> "%LOG%"
curl -s http://localhost:8000/health/ready >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo --- Web --- >> "%LOG%"
curl -s -o NUL -w "web http status %%{http_code}" http://localhost:3000/login >> "%LOG%" 2>&1
echo. >> "%LOG%"
echo RESULT=SUCCESS >> "%LOG%"
start "" http://localhost:3000
exit /b 0

:fail
docker compose -f infra/docker-compose.yml --profile app logs --tail 80 >> "%LOG%" 2>&1
echo RESULT=FAILED (exit %ERRORLEVEL%) >> "%LOG%"
exit /b 1
