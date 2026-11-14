"""Domain enums. Values are stored as native PostgreSQL ENUM types."""
from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class MemberRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MARKETER = "marketer"
    ANALYST = "analyst"
    VIEWER = "viewer"


class CompanySize(StrEnum):
    S1_10 = "1-10"
    S11_50 = "11-50"
    S51_200 = "51-200"
    S201_500 = "201-500"
    S501_1000 = "501-1000"
    S1001_5000 = "1001-5000"
    S5000_PLUS = "5000+"


class CompanyStatus(StrEnum):
    ACTIVE = "active"
    PROSPECT = "prospect"
    CUSTOMER = "customer"
    INACTIVE = "inactive"


class CategoryScope(StrEnum):
    COMPANY = "company"
    CONTACT = "contact"


class SubscriptionStatus(StrEnum):
    SUBSCRIBED = "subscribed"
    PENDING = "pending"
    UNSUBSCRIBED = "unsubscribed"
    BOUNCED = "bounced"
    COMPLAINED = "complained"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VALID = "valid"
    RISKY = "risky"
    INVALID = "invalid"


class LawfulBasis(StrEnum):
    EXPLICIT_CONSENT = "explicit_consent"
    LEGITIMATE_INTEREST = "legitimate_interest"
    CONTRACT = "contract"
    EXISTING_CUSTOMER = "existing_customer"


class SuppressionReason(StrEnum):
    UNSUBSCRIBE = "unsubscribe"
    HARD_BOUNCE = "hard_bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"
    ROLE_ACCOUNT = "role_account"
    INVALID = "invalid"


class EditorType(StrEnum):
    RICH_TEXT = "rich_text"
    DRAG_DROP = "drag_drop"
    HTML = "html"


class TextDirection(StrEnum):
    LTR = "ltr"
    RTL = "rtl"


class BlockType(StrEnum):
    HEADER = "header"
    TEXT = "text"
    IMAGE = "image"
    BUTTON = "button"
    DIVIDER = "divider"
    SPACER = "spacer"
    COLUMNS = "columns"
    FOOTER = "footer"
    HTML = "html"


class Provider(StrEnum):
    SES = "ses"
    SMTP = "smtp"
    DIRECT = "direct"


class IdentityStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PROCESSING = "processing"
    SENDING = "sending"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RecipientStatus(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    COMPLAINED = "complained"
    FAILED = "failed"
    SKIPPED_SUPPRESSED = "skipped_suppressed"


class EventType(StrEnum):
    SEND = "send"
    DELIVERY = "delivery"
    BOUNCE_HARD = "bounce_hard"
    BOUNCE_SOFT = "bounce_soft"
    COMPLAINT = "complaint"
    OPEN = "open"
    CLICK = "click"
    UNSUBSCRIBE = "unsubscribe"
    REJECT = "reject"


class ImportEntity(StrEnum):
    COMPANY = "company"
    CONTACT = "contact"
    SUPPRESSION = "suppression"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
