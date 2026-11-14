@echo off
REM Push local commits on main to GitHub using your own Git credentials.
REM Output: logs\git-push.log
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set LOG=logs\git-push.log
echo === git push %date% %time% === > "%LOG%"
git push origin main >> "%LOG%" 2>&1
if errorlevel 1 (echo RESULT=FAILED >> "%LOG%" & exit /b 1)
git log --oneline -1 >> "%LOG%" 2>&1
echo RESULT=SUCCESS >> "%LOG%"
