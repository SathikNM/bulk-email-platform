# Phase 2 Report — PostgreSQL Schema & Migrations

**Result: complete. 25 tables, 18 enum types, 16 RLS policies and 16 `updated_at` triggers are created by Alembic revision `0001`. 25/25 tests pass against real PostgreSQL 16.15.**

## Completed
| Area | Delivered |
|---|---|
| Models | SQLAlchemy 2.0 typed models in `backend/app/models/` (tenancy, crm, content, sending, ops) |
| Migration | `alembic/versions/0001_initial_schema.py`: extensions (pgcrypto, citext, pg_trgm), sequences, tables, indexes, CHECKs, triggers, `bep_app` role and grants, RLS. Full downgrade path |
| Tenant isolation | FORCE RLS on all 16 workspace tables; `workspace_scope()` / `system_scope()` session helpers |
| Seed | `python -m app.db.seed`: demo workspace, admin user (Argon2id), 28 industries, 8 categories. Safe to re-run |
| Tests | `tests/test_schema.py` (23) + `tests/test_health.py` (2) |
| Windows runner | `scripts/phase2-verify.cmd` runs migrate + seed + tests inside Docker and logs to `logs/` |

## Verification evidence
| Check | Result |
|---|---|
| `alembic upgrade head` on empty DB | ✅ |
| `alembic downgrade base` leaves no tables, enums or sequences | ✅ |
| `alembic check` / model-migration drift | ✅ No differences |
| Duplicate contact email (case-insensitive) in one workspace | ✅ Blocked |
| Same email in different workspaces | ✅ Allowed |
| Soft-deleted contact frees the email | ✅ |
| Company with contacts hard-delete | ✅ Blocked (RESTRICT) |
| Duplicate campaign recipient | ✅ Blocked; `ON CONFLICT DO NOTHING` inserts 0 rows |
| Webhook event replay (`provider_event_id`) | ✅ Blocked |
| Scheduled campaign without time / approval | ✅ Blocked |
| RLS: no workspace set → 0 rows; other workspace rows invisible; cross-workspace insert rejected; cross-workspace update affects 0 rows | ✅ |
| Arabic company names keep their letters in `normalized_name` | ✅ |
| Trigram duplicate suggestion ("Saudi Bin Ladin Group" → "Saudi Binladin Group") | ✅ |

## Pending (next phases)
- Phase 3: authentication + RBAC endpoints, Companies CRUD, tags/categories assignment, duplicate merge, CSV/XLSX import/export, and the Next.js app shell.

## Blockers
- None for Phase 3.
- Phase 8 still needs AWS SES production access and a verified sending domain.
