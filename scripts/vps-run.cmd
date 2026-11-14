@echo off
REM Runs logs\vps-command.sh on the mail VPS (diagnostics / maintenance). Output: logs\vps-run.log
setlocal
cd /d "%~dp0.."
set LOG=logs\vps-run.log
echo === vps-run %date% %time% === > "%LOG%"
call scripts\deploy-config.cmd
set SSHOPT=-i "%USERPROFILE%\.ssh\primecfo_mail_ed25519" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20
ssh %SSHOPT% %VPS_USER%@%VPS_HOST% "bash -s" < logs\vps-command.sh >> "%LOG%" 2>&1
echo EXIT=%errorlevel% >> "%LOG%"
