@echo off
REM Copy to deploy-config.cmd (not committed) and fill in.
set VPS_HOST=203.0.113.10
set VPS_USER=ubuntu
set DOMAIN=bulk.primecfo.sa
set HELO=mail.primecfo.sa
set ADMIN_EMAIL=nmsathik16@gmail.com
REM Space-separated CIDRs allowed to open the admin UI; 0.0.0.0/0 ::/0 = everyone (2FA still applies)
set ADMIN_CIDRS=0.0.0.0/0 ::/0
