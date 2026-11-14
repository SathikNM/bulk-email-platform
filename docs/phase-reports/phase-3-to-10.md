# Phases 3–10 Report

**Result: all modules in the brief are implemented end to end (API + web app). 105 backend integration tests pass against real PostgreSQL 16 + Redis 7, with emails delivered over real SMTP. The web app builds cleanly (lint + type-check) and every page was exercised in a headless browser against the live API.**

| Phase | Delivered | Tests |
|---|---|---|
| 3 Companies | Auth (JWT + rotating refresh, lockout), RBAC, workspaces & members, taxonomy, company CRUD/search/filter/sort, tags/categories, duplicate detection + merge, CSV/XLSX import (async) and export, audit log | 18 |
| 4 Contacts | Contact CRUD, consent records, unsubscribe → suppression, erasure, duplicate report, bulk actions, contact import with consent mapping, email verification (MX) | 14 |
| 5 Segmentation | Rule-tree compiler (nested AND/OR, 16 fields), live total/eligible counts with exclusion reasons, preview, save/edit/duplicate | 8 |
| 6 Email studio | Rendering (variables + fallbacks, sanitiser, RTL, footer, CSS inlining, text part), templates, blocks, images, SMTP + SES providers, sending accounts (encrypted credentials, DNS records), test sends, AI assistant | 11 |
| 7 Campaigns | Draft/validate/approve/schedule/send/pause/resume/cancel/duplicate, state machine, history, recipients, logs, links | 16 (with phase 8) |
| 8 Bulk engine | Idempotent snapshot, SKIP LOCKED batches, per-send eligibility re-check, throttling + daily caps, retries, account-error pause, crash recovery, tracking, RFC 8058 unsubscribe, SES/SNS webhooks | (above) |
| 9 Analytics | KPIs, trends, rates, delivery, growth, distributions, campaign table, daily rollups | 2 (reconciliation) |
| 10 Hardening | Security headers, rate limiting, production config guard, request IDs/logging, non-root Docker images, full-stack compose, CI workflow, deployment & SES guide | 9 |

## Defects found and fixed during verification
| Defect | Impact | Fix |
|---|---|---|
| `INSERT … ON CONFLICT DO NOTHING` returned rowcount −1 (implicit RETURNING) | Webhook replays could be double-counted; import counts wrong | Explicit `RETURNING id` checks |
| Login used strict email validation | The seeded `admin@primecfo.local` could not sign in | Login accepts any address string |
| DB commit ran after the HTTP response | A failed commit could still return 200; queued tasks raced uncommitted data | `Depends(get_db, scope="function")` |
| `updated_at` trigger overwrote retry schedule | Retries could fire immediately | Dedicated `next_attempt_at` column (migration 0002) |
| Draft content and frozen snapshot shared one column | Re-approval would break tracked links | Separate `content_html` (migration 0002) |
| Audience query relied only on RLS | System-scoped callers could see other tenants | Explicit `workspace_id` filter added |
| Closed "Duplicates" dialog evaluated data | Companies page crashed | Render only when open |

## Not verified here (needs your accounts)
- **Real email delivery.** Requires your Amazon SES account in production mode with a verified domain. Follow `docs/06-deployment.md` §3 and send to the SES mailbox simulator. Until then, delivery is verified only against local SMTP capture (Mailpit / aiosmtpd).
- **AI assistant output.** Requires `LLM_API_KEY`; without it the feature correctly reports "not configured".
- **Load at scale** (100k+ recipients) and penetration testing: run in your staging environment.
