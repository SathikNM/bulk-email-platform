# 04 — Implementation Roadmap

Status: **PROPOSED — awaiting approval**. Each phase ends with a report (done / pending / blockers), targeted tests, a DB integrity check and a regression run.

| Phase | Scope | Key deliverables | Exit criteria (tests) |
|---|---|---|---|
| **1. Structure & architecture** ✅ *this commit* | Repo layout, docs, docker-compose, FastAPI skeleton, health checks, CI stub | `docs/01-05`, `backend/app/main.py`, `/health` | App boots; `pytest` health test passes |
| **2. Schema & migrations** | All tables from `02-database-schema.md`, enums, indexes, RLS, triggers, seed (roles, industries, demo workspace) | Alembic revision `0001_initial` | `alembic upgrade head` + `downgrade base` round-trip on real Postgres; constraint tests (dup email, dup recipient) |
| **3. Companies** | Auth + RBAC (needed by every later module), company CRUD, tags/categories, search/filter, duplicate detection + merge, CSV/XLSX import with mapping, export | API + Companies list, profile, import wizard UI | Integration tests against Postgres; 10k-row import benchmark |
| **4. Contacts** | Contact CRUD under companies, consent records, import with consent mapping, duplicate emails, unsubscribe | API + Contacts UI | Import rejects rows without email; dup email blocked; consent history recorded |
| **5. Taxonomy & segmentation** | Industries, categories, tags admin; rule-tree compiler; live count; preview; save/edit/duplicate | `SegmentCompiler`, segment builder UI | Unit tests per operator; the brief's Construction/KSA/Riyadh/CFO example returns correct set; eligible count excludes suppressed |
| **6. Email studio** | GrapesJS builder, TipTap writer, HTML mode, blocks, images (S3/MinIO), variables, EN/AR + RTL, desktop/mobile preview, test send (Mailpit locally), AI assistant | Studio UI, renderer service | Rendered HTML passes inliner; RTL snapshot test; unknown variable → validation warning |
| **7. Campaigns** | 11-step wizard, validation report, approval, schedule, statuses, history, duplicate | Campaign API + wizard UI | State-machine tests (illegal transitions rejected) |
| **8. Bulk engine** | Celery workers, SES provider, rate limiter, retries, idempotent sends, pause/resume, SNS webhooks, tracking pixel/click/unsubscribe, auto-suppression, logs | Workers + provider + webhooks | Send to SES **mailbox simulator** (success, bounce, complaint addresses) end-to-end; duplicate-send test; pause mid-run test |
| **9. Analytics** | Event rollups, KPI tiles, Recharts dashboards, date/campaign filters | Analytics API + dashboard | KPIs reconcile to raw `email_events` counts |
| **10. Hardening** | Rate limiting on API, security headers, input validation review, audit log coverage, secrets via KMS, backups, observability (Sentry, structured logs), load test, deployment (Docker images, CI/CD) | Production checklist | OWASP ASVS L1 checklist; 100k-recipient load test; restore-from-backup drill |

Delivery validity rule: **email sending will not be reported as working until a real SES (or SMTP) account is configured and verified sends succeed.** Phase 6–7 test sends locally go to Mailpit, which is a capture sink, not delivery.

## What I need from you before/while building

| Item | Needed by | Notes |
|---|---|---|
| Approval of decisions D1–D14 (`01-architecture.md`) | Phase 2 | Multi-tenant workspaces in particular |
| AWS account with SES (region, e.g. `me-central-1` or `eu-west-1`), out of sandbox | Phase 8 | Sandbox only sends to verified addresses |
| Verified sending domain + DNS access (SPF, DKIM, DMARC) | Phase 8 | |
| LLM API key for the AI assistant | Phase 6 | Feature can ship disabled without it |
| Hosting target (AWS ECS, a VPS, Azure, etc.) | Phase 10 | |
| Docker Desktop on the dev machine | Phase 2 | For local Postgres/Redis |
