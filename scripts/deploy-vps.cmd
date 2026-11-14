@echo off
REM Deploys the committed code (HEAD) to the mail VPS over SSH. Settings: scripts\deploy-config.cmd
REM Output: logs\deploy.log
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set LOG=logs\deploy.log
echo === deploy %date% %time% === > "%LOG%"
if not exist scripts\deploy-config.cmd (echo Missing scripts\deploy-config.cmd - copy deploy-config.example.cmd >> "%LOG%" & goto fail)
call scripts\deploy-config.cmd
set KEY=%USERPROFILE%\.ssh\primecfo_mail_ed25519
set SSHOPT=-i "%KEY%" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20
echo target %VPS_USER%@%VPS_HOST% domain %DOMAIN% >> "%LOG%"
git archive --format=tar.gz -o logs\release.tgz HEAD >> "%LOG%" 2>&1 || goto fail
scp %SSHOPT% logs\release.tgz infra\prod\server-setup.sh %VPS_USER%@%VPS_HOST%:/tmp/ >> "%LOG%" 2>&1 || goto fail
ssh %SSHOPT% %VPS_USER%@%VPS_HOST% "bash /tmp/server-setup.sh /tmp/release.tgz %DOMAIN% %HELO% %ADMIN_EMAIL% '%ADMIN_CIDRS%'" >> "%LOG%" 2>&1 || goto fail
echo DONE >> "%LOG%"
exit /b 0
:fail
echo RESULT=FAILED >> "%LOG%"
exit /b 1
