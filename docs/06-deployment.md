# 06 — Deployment, Amazon SES Setup & Security Checklist

## 1. Run the full platform locally (Windows, only Docker Desktop needed)

Double-click `scripts\start-platform.cmd`, or run:

```powershell
cd "C:\Prime CFO\Prime CFO\Bulk Email Platefrom"
docker compose -f infra/docker-compose.yml --profile app up -d --build --wait
```

| Service | URL | Purpose |
|---|---|---|
| Web app | http://localhost:3000 | Sign in with the seeded admin (`admin@primecfo.local`) |
| API docs | http://localhost:8000/api/docs | OpenAPI (disabled in production) |
| Mailpit | http://localhost:8025 | Captures emails sent through the local SMTP account |

The `migrate` service runs `alembic upgrade head` and the idempotent seed on every start. The first seed prints a generated admin password in `docker compose logs migrate`. To choose it yourself, set `SEED_ADMIN_PASSWORD` before the first start.

**Local test sending:** add a Sending Account → Provider **SMTP**, host `mailpit`, port `1025`, security **None**. Messages appear in Mailpit; this is capture only, not delivery.

## 2. Production topology

```
Internet ─▶ HTTPS load balancer / reverse proxy (TLS)
              ├── app.example.com      → web  (Next.js, port 3000; proxies /api to api)
              └── track.example.com    → api  (FastAPI: /t/*, /u/*, /webhooks/ses, /assets)
api, worker (Celery, queues celery+send), beat (1 instance) ─▶ PostgreSQL 16 (managed) + Redis 7
worker ─▶ Amazon SES v2 ─▶ SNS topic ─▶ https://track.example.com/webhooks/ses
```

Required production environment (the API **refuses to start** if these are unsafe):

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `SECRET_KEY` | 64 random hex chars (`openssl rand -hex 32`) |
| `CREDENTIALS_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` (store in a secrets manager / KMS; losing it makes stored SES/SMTP credentials unreadable) |
| `COOKIE_SECURE` | `true` |
| `PUBLIC_BASE_URL` | `https://track.example.com` (must be HTTPS) |
| `DATABASE_URL`, `REDIS_URL` | Managed instances, TLS enabled |
| `CELERY_TASK_ALWAYS_EAGER` | `false` |
| `STORAGE_BACKEND` | `s3` with `S3_BUCKET`, `S3_PUBLIC_BASE_URL` (public-read for images only) |

Database role: run the API as a **non-superuser** login role that is a member of `bep_app` (created by migration 0001). Superusers bypass row-level security.

Scale: add `worker` replicas for throughput. The per-account Redis rate limiter keeps the total within the SES send rate. Run exactly **one** `beat`.

Backups: daily PostgreSQL snapshots with point-in-time recovery; test a restore every quarter.

## 3. Amazon SES setup (step by step)

1. **Region.** Choose one close to your audience (e.g. `me-central-1` UAE, `me-south-1` Bahrain, `eu-west-1`). Use the same region in the Sending Account.
2. **Verify the domain.** In the app go to Sending Accounts → Add (provider SES, from `news@yourdomain.com`) → **Verify & DNS**. The platform creates the SES identity and lists the records:
   - 3 × **CNAME** `xxxx._domainkey.yourdomain.com → xxxx.dkim.amazonses.com` (DKIM)
   - **TXT** SPF: merge `include:amazonses.com` into your single existing SPF record
   - **TXT** `_dmarc.yourdomain.com`: start with `v=DMARC1; p=none; rua=mailto:dmarc@yourdomain.com`; move to `quarantine` / `reject` after 2–4 weeks of clean reports.
   - (Recommended) a **custom MAIL FROM** subdomain such as `mail.yourdomain.com` for SPF alignment.
3. **Leave the sandbox.** Request production access in the SES console (describe consent capture, unsubscribe handling, bounce/complaint processing; this platform implements all three).
4. **IAM user or role** with only: `ses:SendRawEmail`, `ses:SendEmail`, `ses:GetEmailIdentity`, `ses:CreateEmailIdentity`, `ses:GetAccount`. Prefer an instance/task role; otherwise paste the key into the Sending Account (encrypted at rest).
5. **Event publishing.** Create a configuration set (e.g. `bep-events`) with an SNS destination for *Send, Delivery, Bounce, Complaint, Reject*. Subscribe the SNS topic over **HTTPS** to `https://track.example.com/webhooks/ses`. The platform verifies every SNS signature, only trusts certificates from `sns.<region>.amazonaws.com`, and auto-confirms the subscription. Enter the configuration set name on the Sending Account.
6. **Send limits.** Set the account's *max per second* and *max per day* at or below the SES quota (button **Quota** shows the live values).
7. **Prove delivery.** Send a test to the SES mailbox simulator and real inboxes:
   - `success@simulator.amazonses.com` → Delivery event
   - `bounce@simulator.amazonses.com` → hard bounce + automatic suppression
   - `complaint@simulator.amazonses.com` → complaint + automatic suppression

   Only after these pass is email delivery considered working.

## 4. Compliance operating rules (built into the platform)

- Contacts are emailable only if: subscribed, active consent record, not suppressed, email not invalid. This is enforced when the recipient list is built **and again immediately before every send**. No setting disables it.
- Imports default to *pending*; consent requires a mapped source **and** date. Public business addresses are never treated as consent.
- Every email carries an RFC 8058 one-click `List-Unsubscribe` header, a visible unsubscribe link and the workspace postal address.
- Hard bounces and complaints are suppressed automatically; complaint suppressions cannot be removed.
- Right to erasure: Contact → erase (owner) anonymises personal data and keeps a suppression entry.
- Configure per workspace which regime applies (KSA PDPL, UAE PDPL, GDPR/PECR, CAN-SPAM) under Settings.

## 5. Security checklist

| Control | Status |
|---|---|
| Argon2id passwords, strength rules, login lockout (5 failures / 15 min) + IP rate limits | ✅ |
| 15-minute JWT access tokens; rotating httpOnly refresh cookies with reuse detection | ✅ |
| RBAC (owner/admin/marketer/analyst/viewer) on every endpoint; tested role matrix | ✅ |
| Tenant isolation: workspace header + PostgreSQL FORCE row-level security | ✅ |
| Input validation (Pydantic), whitelisted segment compiler (no user SQL), HTML sanitiser | ✅ |
| Provider credentials Fernet-encrypted, write-only in the API | ✅ |
| Signed tracking/unsubscribe tokens; click redirect only to stored URLs | ✅ |
| SNS signature verification for webhooks | ✅ |
| Security headers (CSP on API, nosniff, frame-deny, HSTS in production), request IDs, JSON access logs | ✅ |
| Production config guard (refuses unsafe settings), OpenAPI disabled in production | ✅ |
| Audit log of data changes, approvals, sends, exports, suppression changes | ✅ |
| Containers run as non-root | ✅ |
| CI: lint, migration drift check, 105 integration tests, frontend lint/type-check/build | ✅ |
| Before go-live: penetration test, load test at expected volume, backup restore drill, Sentry/APM | ⏳ Your environment |

## Built-in direct delivery (no outside email service)

Sending accounts with provider **Built-in (direct delivery)** make the platform its own mail server: it looks up each
recipient's MX hosts, delivers on port 25 with opportunistic STARTTLS, signs every message with a DKIM key it
generates per account, retries 4xx replies with back-off, suppresses addresses that hard-bounce (5.1.x), paces
delivery per destination (Google, Microsoft, …) and warms new IPs up automatically
(50/day → 10,000/day by day 23 → the configured limit by day 35).

Infrastructure it needs (checked by **Verify & DNS**, which also prints the exact records):

| Requirement | Where it is set |
|---|---|
| Fixed public IP, outbound port 25 open | Internet provider or server host |
| Reverse DNS (PTR) of that IP = HELO name, e.g. `mail.primecfo.sa` | Internet provider or server host |
| `A mail.primecfo.sa → IP` | Domain DNS |
| SPF including `ip4:<IP>` (keeps existing senders) | Domain DNS |
| DKIM TXT `bep._domainkey.<domain>` | Domain DNS (value shown in the platform) |
| DMARC TXT `_dmarc.<domain>` | Domain DNS |

The platform must run on that machine 24/7 (workers deliver and retry in the background).
