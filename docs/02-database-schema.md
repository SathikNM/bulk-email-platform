# 02 — Database Schema & ER Diagram (PostgreSQL 16)

Status: **PROPOSED — awaiting approval**

Conventions
- Primary keys: `UUID` (`gen_random_uuid()`); human-readable codes (`COMP-000123`) as separate `code` columns where users need them.
- Every business table has `workspace_id`, `created_at`, `updated_at` (trigger-maintained), and `created_by` where relevant.
- Soft delete via `deleted_at` on companies, contacts, templates and campaigns (audit and analytics stay intact).
- Emails stored as `CITEXT` for case-insensitive uniqueness.
- Enum-like columns use Postgres `ENUM` types managed by Alembic.

## 1. ER diagram

```mermaid
erDiagram
  workspaces ||--o{ workspace_members : has
  users ||--o{ workspace_members : joins
  workspaces ||--o{ companies : owns
  workspaces ||--o{ contacts : owns
  industries ||--o{ companies : classifies
  categories ||--o{ company_categories : ""
  companies ||--o{ company_categories : ""
  companies ||--o{ contacts : employs
  tags ||--o{ company_tags : ""
  companies ||--o{ company_tags : ""
  tags ||--o{ contact_tags : ""
  contacts ||--o{ contact_tags : ""
  categories ||--o{ contacts : "contact category"
  contacts ||--o{ consent_records : has
  workspaces ||--o{ suppressions : maintains
  workspaces ||--o{ segments : defines
  workspaces ||--o{ email_templates : stores
  email_templates ||--o{ email_blocks : "composed of"
  workspaces ||--o{ sending_accounts : configures
  campaigns }o--|| segments : targets
  campaigns }o--|| email_templates : uses
  campaigns }o--|| sending_accounts : "sends via"
  campaigns ||--o{ campaign_recipients : snapshots
  contacts ||--o{ campaign_recipients : receives
  campaign_recipients ||--o{ email_events : generates
  campaigns ||--o{ tracked_links : contains
  campaigns ||--o{ campaign_daily_stats : "rolls up"
  workspaces ||--o{ import_jobs : runs
  users ||--o{ audit_logs : performs

  workspaces { uuid id PK; text name; text slug UK; text default_locale; text legal_address; jsonb compliance_settings }
  users { uuid id PK; citext email UK; text password_hash; text full_name; bool is_active; bool is_superadmin; timestamptz last_login_at }
  workspace_members { uuid workspace_id PK,FK; uuid user_id PK,FK; enum role }
  industries { uuid id PK; uuid workspace_id FK; text name; uuid parent_id FK }
  categories { uuid id PK; uuid workspace_id FK; enum scope; text name; text color }
  tags { uuid id PK; uuid workspace_id FK; text name; text color }
  companies { uuid id PK; uuid workspace_id FK; text code; text name; text normalized_name; uuid industry_id FK; text business_type; text country_code; text city; text website; text domain; enum company_size; numeric annual_revenue; enum status; text data_source; text notes }
  contacts { uuid id PK; uuid workspace_id FK; uuid company_id FK; text code; text first_name; text last_name; text job_title; text department; citext email; text phone; text country_code; text city; uuid category_id FK; enum subscription_status; text consent_source; timestamptz consent_date; enum email_verification_status; text notes }
  consent_records { uuid id PK; uuid contact_id FK; enum lawful_basis; text source; text evidence; inet ip_address; timestamptz granted_at; timestamptz withdrawn_at }
  suppressions { uuid id PK; uuid workspace_id FK; citext email; enum reason; text source; timestamptz created_at }
  segments { uuid id PK; uuid workspace_id FK; text name; jsonb rules; int cached_count; timestamptz count_refreshed_at }
  email_templates { uuid id PK; uuid workspace_id FK; text name; text subject; text preheader; enum editor_type; jsonb design_json; text html; text text_body; enum direction; text locale; bool is_draft }
  email_blocks { uuid id PK; uuid workspace_id FK; uuid template_id FK; text name; enum block_type; jsonb content; int position; bool is_reusable }
  sending_accounts { uuid id PK; uuid workspace_id FK; enum provider; text from_email; text from_name; text reply_to; text domain; bytea encrypted_credentials; text region; text configuration_set; int max_per_second; int max_per_day; enum verification_status }
  campaigns { uuid id PK; uuid workspace_id FK; text name; uuid segment_id FK; uuid template_id FK; uuid sending_account_id FK; text subject; text preheader; text html_snapshot; jsonb manual_contact_ids; enum status; timestamptz scheduled_at; timestamptz started_at; timestamptz completed_at; uuid approved_by FK; timestamptz approved_at; uuid duplicated_from FK }
  campaign_recipients { uuid id PK; uuid campaign_id FK; uuid contact_id FK; citext email; jsonb merge_data; enum status; text provider_message_id UK; int attempts; text last_error; timestamptz sent_at; timestamptz delivered_at; timestamptz first_opened_at; timestamptz first_clicked_at }
  email_events { bigint id PK; uuid workspace_id FK; uuid campaign_id FK; uuid recipient_id FK; enum event_type; text provider_event_id UK; text url; text user_agent; inet ip; jsonb raw; timestamptz occurred_at }
  tracked_links { uuid id PK; uuid campaign_id FK; text original_url; text token UK }
  campaign_daily_stats { uuid campaign_id PK,FK; date day PK; int sent; int delivered; int bounced; int opened; int unique_opened; int clicked; int unique_clicked; int unsubscribed; int complained }
  import_jobs { uuid id PK; uuid workspace_id FK; enum entity; text file_key; jsonb column_mapping; enum status; int total_rows; int inserted; int updated; int skipped; jsonb errors }
  audit_logs { bigint id PK; uuid workspace_id FK; uuid user_id FK; text action; text entity_type; uuid entity_id; jsonb before; jsonb after; inet ip; timestamptz created_at }
```

`company_categories`, `company_tags` and `contact_tags` are pure join tables: composite PK (`parent_id`, `tag_id` / `category_id`) with FKs `ON DELETE CASCADE`.

## 2. Enums

| Enum | Values |
|---|---|
| `member_role` | owner, admin, marketer, analyst, viewer |
| `company_size` | 1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5000+ |
| `company_status` | active, prospect, customer, inactive |
| `category_scope` | company, contact |
| `subscription_status` | subscribed, pending, unsubscribed, bounced, complained |
| `verification_status` | unverified, valid, risky, invalid |
| `lawful_basis` | explicit_consent, legitimate_interest, contract, existing_customer |
| `suppression_reason` | unsubscribe, hard_bounce, complaint, manual, role_account, invalid |
| `editor_type` | rich_text, drag_drop, html |
| `text_direction` | ltr, rtl |
| `block_type` | header, text, image, button, divider, spacer, columns, footer, html |
| `provider` | ses, smtp |
| `campaign_status` | draft, scheduled, processing, sending, completed, paused, failed, cancelled |
| `recipient_status` | queued, sending, sent, delivered, bounced, complained, failed, skipped_suppressed |
| `event_type` | send, delivery, bounce_hard, bounce_soft, complaint, open, click, unsubscribe, reject |

## 3. Constraints & integrity

| Table | Constraint |
|---|---|
| contacts | `UNIQUE (workspace_id, email) WHERE deleted_at IS NULL` (duplicate email detection) |
| companies | `UNIQUE (workspace_id, domain) WHERE domain IS NOT NULL AND deleted_at IS NULL`; duplicate *suggestions* via `pg_trgm` similarity on `normalized_name` |
| contacts.company_id | FK → companies `ON DELETE RESTRICT` (company with contacts must be archived, not hard-deleted) |
| suppressions | `UNIQUE (workspace_id, email)` |
| campaign_recipients | `UNIQUE (campaign_id, contact_id)`, `UNIQUE (campaign_id, email)` (duplicate-send protection) |
| email_events | `UNIQUE (provider_event_id)` (webhook replay idempotency) |
| tags / categories / industries | `UNIQUE (workspace_id, lower(name))` (+ scope for categories) |
| campaigns | `CHECK (status <> 'scheduled' OR scheduled_at IS NOT NULL)` |

## 4. Indexes

| Index | Purpose |
|---|---|
| `contacts (workspace_id, subscription_status, email_verification_status)` | Eligibility filtering |
| `contacts (workspace_id, company_id)` | Company profile → contacts |
| `contacts USING gin (job_title gin_trgm_ops)`, same for `first_name`, `last_name`, `email` | Fast partial-text search |
| `companies (workspace_id, industry_id, country_code, city, company_size)` | Segment filters |
| `companies USING gin (normalized_name gin_trgm_ops)` | Search + duplicate detection |
| `contact_tags (tag_id, contact_id)`, `company_tags (tag_id, company_id)` | Tag filters |
| `campaign_recipients (campaign_id, status)` | Worker claiming + progress |
| `email_events (campaign_id, event_type, occurred_at)` | Analytics |
| `email_events (workspace_id, occurred_at)` (BRIN) | Time-range scans on a large append-only table |
| `audit_logs (workspace_id, entity_type, entity_id)` | Record history |

Pagination: keyset (`created_at, id`) for large lists; offset for small admin lists.

## 5. Data isolation

- Every query passes through a `WorkspaceScopedSession` that injects `workspace_id`.
- Postgres RLS policies (`USING workspace_id = current_setting('app.workspace_id')::uuid`) as defence in depth; the API sets `SET LOCAL app.workspace_id` per request transaction.

## 6. Segment rule format (stored in `segments.rules`)

```json
{
  "op": "and",
  "rules": [
    {"field": "industry", "operator": "in", "value": ["Construction"]},
    {"field": "country", "operator": "eq", "value": "SA"},
    {"field": "city", "operator": "eq", "value": "Riyadh"},
    {"op": "or", "rules": [
      {"field": "job_title", "operator": "contains", "value": "CFO"},
      {"field": "job_title", "operator": "contains", "value": "Finance Manager"}
    ]},
    {"field": "subscription_status", "operator": "eq", "value": "subscribed"}
  ]
}
```

Allowed fields: industry, country, city, company, company_size, job_title, department, contact_category, company_category, tags, subscription_status, email_verification_status, created_at.
Operators: eq, neq, in, not_in, contains, not_contains, starts_with, is_empty, is_not_empty, before, after.
The compiler whitelists fields and operators and always ANDs the eligibility gate onto the "eligible count".
