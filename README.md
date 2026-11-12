# Bulk Email Platform

Email marketing and bulk email management platform: company/contact database, audience segmentation, email studio, campaigns, SES-based bulk sending, and analytics.

**Current status: Phase 1 complete (architecture + project structure). Awaiting architecture approval before Phase 2.**

## Docs
1. [System architecture & design decisions](docs/01-architecture.md)
2. [Database schema & ER diagram](docs/02-database-schema.md)
3. [API endpoints](docs/03-api-endpoints.md)
4. [Implementation roadmap](docs/04-roadmap.md)
5. [Dependencies & risks](docs/05-dependencies-and-risks.md)

## Stack
Next.js / React / TypeScript / Tailwind / shadcn/ui · FastAPI (Python) · PostgreSQL · Redis + Celery · Amazon SES · Recharts · GrapesJS + TipTap

## Run locally
```bash
# 1. Infrastructure (needs Docker Desktop)
docker compose -f infra/docker-compose.yml up -d

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp ../.env.example .env
uvicorn app.main:app --reload       # http://localhost:8000/api/docs
pytest
```

## Phase status
| Phase | Status |
|---|---|
| 1. Structure & architecture | ✅ Done |
| 2. Schema & migrations | ⏳ Awaiting approval |
| 3–10 | Pending |
