#!/usr/bin/env bash
# Runs ON the VPS (invoked by scripts/deploy-vps.cmd). Idempotent: safe to re-run for every update.
#   bash server-setup.sh <release.tgz> <domain> <helo-hostname> <admin-email> [admin-cidrs]
set -euo pipefail
REL="$1"; DOMAIN="$2"; HELO="$3"; ADMIN_EMAIL="$4"; CIDRS="${5:-0.0.0.0/0 ::/0}"
APP=/opt/bulk-email
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo -n"

echo "== system"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO usermod -aG docker "$(id -un)" || true
fi
DOCKER="$SUDO docker"
if command -v ufw >/dev/null; then
  for p in 22 25 80 443; do $SUDO ufw allow "$p/tcp" >/dev/null; done
  $SUDO ufw --force enable >/dev/null
fi

echo "== code"
$SUDO mkdir -p "$APP/src" "$APP/backups"
$SUDO tar -xzf "$REL" -C "$APP/src"

echo "== config"
ENV="$APP/.env.prod"
if [ ! -f "$ENV" ]; then
  FERNET=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
  ADMIN_PW="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)Aa1!"
  $SUDO tee "$ENV" >/dev/null <<CONF
DOMAIN=$DOMAIN
HELO_HOSTNAME=$HELO
SECRET_KEY=$(openssl rand -hex 32)
CREDENTIALS_ENCRYPTION_KEY=$FERNET
POSTGRES_PASSWORD=$(openssl rand -hex 24)
SEED_ADMIN_EMAIL=$ADMIN_EMAIL
SEED_ADMIN_PASSWORD=$ADMIN_PW
ADMIN_ALLOWED_CIDRS=$CIDRS
BACKUP_DIR=$APP/backups
CONF
  $SUDO chmod 600 "$ENV"
  echo "FIRST-RUN ADMIN LOGIN: $ADMIN_EMAIL / $ADMIN_PW  (change it and turn on two-factor sign-in)"
else
  $SUDO sed -i "s|^ADMIN_ALLOWED_CIDRS=.*|ADMIN_ALLOWED_CIDRS=$CIDRS|; s|^DOMAIN=.*|DOMAIN=$DOMAIN|; s|^HELO_HOSTNAME=.*|HELO_HOSTNAME=$HELO|" "$ENV"
fi

echo "== start"
cd "$APP/src"
$DOCKER compose -f infra/docker-compose.prod.yml --env-file "$ENV" up -d --build --remove-orphans
sleep 8
$DOCKER compose -f infra/docker-compose.prod.yml --env-file "$ENV" ps --format 'table {{.Service}}\t{{.Status}}'

echo "== checks"
echo "public IP: $(curl -fsS https://api.ipify.org || echo unknown)"
echo "reverse DNS: $(getent hosts "$(curl -fsS https://api.ipify.org 2>/dev/null)" | awk '{print $2}' || true)"
timeout 8 bash -c 'echo > /dev/tcp/gmail-smtp-in.l.google.com/25' && echo "outbound 25: open" || echo "outbound 25: BLOCKED"
for i in $(seq 1 40); do
  if $DOCKER compose -f infra/docker-compose.prod.yml --env-file "$ENV" exec -T api \
       python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health/ready',timeout=5)" 2>/dev/null; then
    echo "platform: up"; break
  fi
  sleep 5
done
$DOCKER compose -f infra/docker-compose.prod.yml --env-file "$ENV" logs --tail 3 caddy 2>&1 | tail -3
echo "RESULT=SUCCESS"
