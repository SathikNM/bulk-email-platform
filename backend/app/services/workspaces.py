"""Workspace bootstrap (default taxonomy) used by seed and workspace creation."""
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Category, Industry
from app.models.enums import CategoryScope

INDUSTRIES = [
    "Construction", "Real Estate", "Manufacturing", "Retail", "Wholesale & Distribution",
    "Healthcare", "Education", "Financial Services", "Banking", "Insurance",
    "Information Technology", "Software & SaaS", "Telecommunications", "Oil & Gas",
    "Energy & Utilities", "Logistics & Transportation", "Hospitality & Tourism", "Food & Beverage",
    "Professional Services", "Legal", "Government & Public Sector", "Non-Profit",
    "Media & Entertainment", "Agriculture", "Automotive", "Mining", "Pharmaceuticals", "E-commerce",
]
COMPANY_CATEGORIES = ["Prospect", "Client", "Partner", "Vendor"]
CONTACT_CATEGORIES = ["Decision Maker", "Influencer", "Finance", "Operations"]


def bootstrap_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    existing = set(db.scalars(sa.select(Industry.name).where(Industry.workspace_id == workspace_id)))
    db.add_all(Industry(workspace_id=workspace_id, name=n) for n in INDUSTRIES if n not in existing)
    cats = set(db.execute(sa.select(Category.scope, Category.name)
                          .where(Category.workspace_id == workspace_id)).all())
    for scope, names in ((CategoryScope.COMPANY, COMPANY_CATEGORIES),
                         (CategoryScope.CONTACT, CONTACT_CATEGORIES)):
        db.add_all(Category(workspace_id=workspace_id, scope=scope, name=n)
                   for n in names if (scope, n) not in cats)
