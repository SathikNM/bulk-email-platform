# 05 — Dependencies & Risks

## Backend (Python 3.12)
| Package | Use |
|---|---|
| fastapi, uvicorn[standard] | API server |
| pydantic v2, pydantic-settings, email-validator | Schemas, config, email syntax |
| sqlalchemy 2.x, asyncpg, psycopg[binary], alembic | ORM, drivers, migrations |
| celery[redis], redis | Background jobs, rate limiter |
| boto3 | Amazon SES v2, S3 |
| argon2-cffi, pyjwt, cryptography | Password hashing, JWT, Fernet credential encryption |
| openpyxl, pandas (import only) | CSV/XLSX import/export |
| jinja2 (sandboxed), premailer, bleach | Personalisation, CSS inlining, HTML sanitisation |
| dnspython | MX check / SPF-DKIM-DMARC lookup |
| httpx | SNS signature cert fetch, LLM API |
| pytest, pytest-asyncio, testcontainers, ruff, mypy | Testing and quality |

## Frontend
| Package | Use |
|---|---|
| next 14+, react, typescript | App |
| tailwindcss, shadcn/ui (Radix), lucide-react | UI |
| @tanstack/react-query, @tanstack/react-table | Data fetching, advanced tables |
| react-hook-form, zod | Forms + validation |
| recharts | Charts |
| grapesjs, grapesjs-preset-newsletter, @tiptap/react | Email editors |
| next-intl | EN/AR i18n with RTL |
| openapi-typescript | Typed API client |

## Infrastructure
PostgreSQL 16 (pg_trgm, citext, pgcrypto), Redis 7, SeaweedFS (local S3; MinIO images were withdrawn), Mailpit (local SMTP capture), Docker Compose.

## Risks
| Risk | Impact | Mitigation |
|---|---|---|
| Sending to lists without valid consent | Legal exposure (PDPL/GDPR), domain blacklisting | Eligibility gate, imported contacts default to `pending`, consent mapping required, double opt-in option |
| SES sandbox / low quota | Can't send at scale | Request production access early; quota surfaced in UI; rate limiter respects it |
| Domain reputation (bounces > 5%, complaints > 0.1%) | SES account suspension | Auto-suppress hard bounces/complaints; pre-send verification; warm-up throttling; alert thresholds |
| Duplicate sends on worker crash | Customer complaints | Row-level claim with `SKIP LOCKED`, unique constraints, status machine |
| Open-rate inflation (Apple MPP, image proxies) | Misleading KPIs | Flag machine opens; lead with click rate in reporting |
| Arabic rendering in Outlook | Broken layouts | Table-based layout, `dir="rtl"` on table cells, Litmus/Email on Acid check before launch |
| GrapesJS learning curve / email HTML quirks | Slower Phase 6 | Start from newsletter preset; constrain blocks |
| Cross-tenant data leakage | Severe | Workspace scoping + RLS + tests that try cross-workspace access |
| Credential leakage | Account takeover | Encrypted at rest, write-only API fields, KMS in production, audit on change |
| Large imports (100k+ rows) | Timeouts | Async import jobs, streaming parse, batch upserts (`COPY` into staging table) |
| No Docker on the current dev VM | Can't run Postgres integration tests here | Run locally with Docker Desktop or use a managed dev DB |
