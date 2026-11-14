# Bulk Email Platform

Email marketing and bulk email management platform: company and contact database, consent-aware audience segmentation, email studio (drag-and-drop, rich text, HTML, English/Arabic RTL), campaign approval and scheduling, Amazon SES bulk sending with bounce/complaint handling, tracking, and analytics. Multi-tenant: each client works in an isolated workspace.

**Status: all 10 phases complete.** See the [phase reports](docs/phase-reports/).

## Quick start (Windows, Docker Desktop only)

1. Double-click **`scripts\start-platform.cmd`**. The first run builds the images (5–10 min) and then opens http://localhost:3000.
2. Sign in as `admin@primecfo.local`. The password is the one printed by the first seed (`logs\phase2-verify.log` from Phase 2, or `docker compose -f infra/docker-compose.yml logs migrate`).
3. Settings → set your **postal address**. Sending Accounts → add **SMTP** `mailpit:1025` (security *None*) for local tests, or Amazon SES for real sending ([setup guide](docs/06-deployment.md#3-amazon-ses-setup-step-by-step)).
4. Import companies/contacts → build a segment → design a template → create a campaign → test → approve → send.

Other scripts: `scripts\verify.cmd` (migrations + 105 integration tests in Docker → `logs\verify.log`), `scripts\stop-platform.cmd`, `scripts\git-push.cmd`.

## Docs
1. [Architecture & decisions](docs/01-architecture.md)
2. [Database schema & ER diagram](docs/02-database-schema.md)
3. [API endpoints](docs/03-api-endpoints.md)
4. [Roadmap](docs/04-roadmap.md)
5. [Dependencies & risks](docs/05-dependencies-and-risks.md)
6. [Deployment, SES setup & security checklist](docs/06-deployment.md)

## Stack
Next.js 16 · React 19 · TypeScript · Tailwind 4 · TanStack Query · Recharts · GrapesJS · TipTap | FastAPI · SQLAlchemy 2 · Alembic · Celery · PostgreSQL 16 (RLS) · Redis 7 · Amazon SES v2 / SMTP

## Development without Docker for the app
```bash
docker compose -f infra/docker-compose.yml up -d          # postgres, redis, s3, mailpit
cd backend && pip install -e ".[dev]" && cp ../.env.example .env
python -m alembic upgrade head && python -m app.db.seed
uvicorn app.main:app --reload                               # API  http://localhost:8000/api/docs
celery -A app.workers.celery_app:celery worker -Q celery,send -B   # worker + scheduler
pytest                                                      # 105 integration tests (uses <db>_test)
cd ../frontend && npm install && npm run dev                # Web  http://localhost:3000
```

## Phase status
| Phase | Status |
|---|---|
| 1. Structure & architecture | ✅ |
| 2. Schema & migrations | ✅ ([report](docs/phase-reports/phase-2.md)) |
| 3. Companies | ✅ |
| 4. Contacts | ✅ |
| 5. Categories, tags & segmentation | ✅ |
| 6. Email studio & templates | ✅ |
| 7. Campaign management | ✅ |
| 8. Bulk email engine | ✅ (real delivery requires your SES account) |
| 9. Analytics | ✅ |
| 10. Security & production readiness | ✅ ([report](docs/phase-reports/phase-3-to-10.md)) |
