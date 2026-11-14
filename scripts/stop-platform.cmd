@echo off
REM Stop the application containers (data volumes are kept).
cd /d "%~dp0.."
docker compose -f infra/docker-compose.yml --profile app stop api worker beat web
