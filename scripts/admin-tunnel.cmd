@echo off
REM Break-glass admin access: opens an SSH tunnel to the mail VPS, then browse https://localhost:8443
REM Keep this window open while you use the admin UI; close it to end the tunnel.
setlocal
cd /d "%~dp0.."
call scripts\deploy-config.cmd
echo Tunnel open. Browse https://localhost:8443 (accept the certificate warning). Close this window to stop.
start "" https://localhost:8443
ssh -i "%USERPROFILE%\.ssh\primecfo_mail_ed25519" -o ExitOnForwardFailure=yes -N -L 8443:localhost:8443 %VPS_USER%@%VPS_HOST%
