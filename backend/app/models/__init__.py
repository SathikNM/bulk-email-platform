"""Import every model so Base.metadata is complete (Alembic, tests)."""
from app.db.base import Base
from app.models.content import EmailBlock, EmailTemplate, Segment
from app.models.crm import (
    Category,
    Company,
    CompanyCategory,
    CompanyTag,
    ConsentRecord,
    Contact,
    ContactTag,
    Industry,
    Suppression,
    Tag,
)
from app.models.mailbox import MailMessage
from app.models.ops import AuditLog, ImportJob
from app.models.sending import (
    Campaign,
    CampaignDailyStat,
    CampaignRecipient,
    EmailEvent,
    SendingAccount,
    TrackedLink,
)
from app.models.tenancy import RefreshToken, User, Workspace, WorkspaceMember

# Tables carrying workspace_id that get Row-Level Security.
RLS_TABLES = [
    "industries", "categories", "tags", "companies", "contacts", "consent_records",
    "suppressions", "segments", "email_templates", "email_blocks", "sending_accounts",
    "campaigns", "campaign_recipients", "email_events", "campaign_daily_stats", "import_jobs",
]
# Workspace tables added after the initial schema (their RLS policies live in later migrations).
LATER_RLS_TABLES = ["mail_messages"]

# Tables with an updated_at column maintained by trigger.
UPDATED_AT_TABLES = [
    "workspaces", "users", "workspace_members", "industries", "categories", "tags", "companies",
    "contacts", "segments", "email_templates", "email_blocks", "sending_accounts", "campaigns",
    "campaign_recipients", "campaign_daily_stats", "import_jobs",
]

__all__ = [
    "Base", "RLS_TABLES", "UPDATED_AT_TABLES",
    "Workspace", "User", "WorkspaceMember", "RefreshToken",
    "Industry", "Category", "Tag", "Company", "CompanyCategory", "CompanyTag",
    "Contact", "ContactTag", "ConsentRecord", "Suppression",
    "Segment", "EmailTemplate", "EmailBlock",
    "SendingAccount", "Campaign", "CampaignRecipient", "TrackedLink", "EmailEvent",
    "CampaignDailyStat", "ImportJob", "AuditLog",
]
