# 03 — API Structure (REST, `/api/v1`)

Status: **PROPOSED — awaiting approval**

- Auth: `Authorization: Bearer <access JWT>`; workspace selected via `X-Workspace-Id` header and checked against membership.
- Errors: RFC 7807 problem+json. Validation errors return field-level detail.
- Lists: `?q=&page_size=&cursor=&sort=&filter[field]=` with keyset cursors.
- OpenAPI served at `/api/docs`; the frontend client is generated from it.
- Role column: minimum role required (O=owner, A=admin, M=marketer, An=analyst, V=viewer).

## Auth & users
| Method | Path | Role | Purpose |
|---|---|---|---|
| POST | /auth/login | — | Email + password → access token, refresh cookie |
| POST | /auth/refresh | — | Rotate refresh token |
| POST | /auth/logout | V | Revoke refresh token |
| GET | /auth/me | V | Current user + workspaces + roles |
| POST | /auth/password/forgot, /auth/password/reset | — | Reset flow |
| GET/POST | /workspaces | V / superadmin | List / create workspaces |
| GET/POST/PATCH/DELETE | /workspaces/{id}/members | A | Manage members and roles |

## Companies (Module 1)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | /companies | V | Search, filter, paginate |
| POST | /companies | M | Create |
| GET | /companies/{id} | V | Full profile (contacts, tags, categories, campaign history) |
| PATCH | /companies/{id} | M | Update |
| DELETE | /companies/{id} | A | Soft delete (blocked if active contacts unless `?cascade_archive=true`) |
| POST | /companies/{id}/tags, DELETE /companies/{id}/tags/{tag_id} | M | Tag assignment |
| PUT | /companies/{id}/categories | M | Replace category set |
| GET | /companies/duplicates | M | Duplicate candidates (domain match + name similarity) |
| POST | /companies/merge | A | Merge duplicates |
| POST | /companies/import | M | Upload CSV/XLSX → `import_job` (async) |
| GET | /companies/export | An | CSV/XLSX export of current filter (async for >10k rows) |

## Contacts (Module 2)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | /contacts | V | Search by name, company, job title, email; filter by department, title, status |
| POST | /contacts | M | Create (requires company_id) |
| GET/PATCH/DELETE | /contacts/{id} | V/M/A | Read / update / soft delete |
| POST/DELETE | /contacts/{id}/tags | M | Tags |
| GET/POST | /contacts/{id}/consents | V/M | Consent history / record consent |
| POST | /contacts/{id}/unsubscribe | M | Manual unsubscribe (adds suppression) |
| GET | /contacts/duplicates | M | Duplicate emails / near-duplicate names |
| POST | /contacts/import | M | CSV/XLSX import with column mapping + consent mapping |
| GET | /contacts/export | An | Export |
| POST | /contacts/bulk | M | Bulk tag / category / status update |

## Imports
| GET | /imports/{id} | M | Job progress, row errors |
| POST | /imports/preview | M | Parse first 20 rows, auto-suggest column mapping |
| GET | /imports/{id}/errors.csv | M | Download rejected rows |

## Taxonomy (Module 3)
| GET/POST/PATCH/DELETE | /industries, /categories, /tags | V/M | CRUD |

## Segments (Module 3)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET/POST | /segments | V/M | List / create |
| GET/PATCH/DELETE | /segments/{id} | V/M/M | Read / edit / delete |
| POST | /segments/{id}/duplicate | M | Duplicate |
| POST | /segments/count | V | Live count for an unsaved rule tree: `{total, eligible, excluded_by_reason}` |
| POST | /segments/preview | V | First N matching contacts for an unsaved rule tree |
| GET | /segments/{id}/contacts | V | Paginated members |
| GET | /segments/fields | V | Filterable fields, operators, value options |

## Email studio (Module 4)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET/POST | /templates | V/M | List / create |
| GET/PATCH/DELETE | /templates/{id} | V/M/M | CRUD (save draft) |
| POST | /templates/{id}/duplicate | M | Duplicate |
| POST | /templates/{id}/render | V | Render with sample or chosen contact → HTML (desktop/mobile handled client-side) |
| POST | /templates/{id}/test-send | M | Send test to up to 5 addresses (real provider) |
| GET/POST/DELETE | /blocks | V/M | Reusable blocks |
| POST | /assets | M | Image upload → signed S3 URL |
| POST | /ai/generate | M | `{kind: subject|body|marketing|follow_up|cta, language: en|ar, tone, context}` → suggestions |

## Campaigns (Module 5)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET/POST | /campaigns | V/M | History (filter by status/date) / create draft |
| GET/PATCH/DELETE | /campaigns/{id} | V/M/A | Read / edit draft / delete draft |
| POST | /campaigns/{id}/duplicate | M | Duplicate |
| POST | /campaigns/{id}/validate | M | Recipient validation report (eligible, suppressed, invalid, duplicates, missing merge fields) |
| POST | /campaigns/{id}/test-send | M | Test email |
| POST | /campaigns/{id}/approve | A | Approval (records approver); optional `scheduled_at` |
| POST | /campaigns/{id}/send | A | Send now (must be approved) |
| POST | /campaigns/{id}/pause, /resume, /cancel | A | Control |
| GET | /campaigns/{id}/recipients | V | Per-recipient delivery status |
| GET | /campaigns/{id}/logs | An | Sending log |

## Sending accounts (Module 6)
| GET/POST/PATCH/DELETE | /sending-accounts | A | Configure SES/SMTP (credentials write-only) |
| POST | /sending-accounts/{id}/verify | A | Check identity + fetch SPF/DKIM/DMARC records and status |
| GET | /sending-accounts/{id}/quota | A | Provider quota and current usage |

## Suppressions & compliance
| GET/POST/DELETE | /suppressions | V/A | List / add / remove (removal requires admin + reason, audited) |
| POST | /suppressions/import | A | Bulk import suppression list |
| GET | /audit-logs | A | Audit trail |
| POST | /contacts/{id}/erase | O | Right-to-erasure (anonymise, keep suppression hash) |

## Analytics (Module 7)
| GET | /analytics/overview?from=&to=&campaign_id= | An | KPI tiles |
| GET | /analytics/trends | An | Sent/delivered/open/click over time |
| GET | /analytics/campaigns | An | Campaign-wise table |
| GET | /analytics/audience-growth | An | Contacts and subscribers over time |
| GET | /analytics/distribution?by=industry|country | An | Contact distribution |

## Public (unauthenticated, signed tokens)
| GET | /t/o/{token}.gif | Open pixel |
| GET | /t/c/{token} | Click redirect (only to stored `tracked_links`, no open redirect) |
| GET/POST | /u/{token} | Unsubscribe page + RFC 8058 one-click POST |
| POST | /webhooks/ses | SNS-signed SES events (signature verified) |
| GET | /health, /health/ready | Liveness / readiness (DB + Redis) |
