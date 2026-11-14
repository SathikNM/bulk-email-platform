"""Module 7: analytics dashboard endpoints (filterable by date range and campaign)."""
import uuid
from datetime import date, datetime, time, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, Query

from app.core.deps import Analyst, Ctx
from app.models import (
    Campaign,
    CampaignDailyStat,
    CampaignRecipient,
    Company,
    ConsentRecord,
    Contact,
    EmailEvent,
    Industry,
)
from app.models.enums import EventType, RecipientStatus
from app.services import analytics as an
from app.services.compliance import eligibility_clause

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _bounds(d_from: date | None, d_to: date | None) -> tuple[date, date, datetime, datetime]:
    start, end = an.date_range(d_from, d_to)
    return start, end, datetime.combine(start, time.min, timezone.utc), \
        datetime.combine(end + timedelta(days=1), time.min, timezone.utc)


@router.post("/refresh")
def refresh(ctx: Ctx = Analyst):
    ids = list(ctx.db.scalars(sa.select(Campaign.id).where(Campaign.started_at.isnot(None))))
    for cid in ids:
        an.rollup_campaign(ctx.db, cid)
    return {"campaigns_refreshed": len(ids)}


@router.get("/overview")
def overview(ctx: Ctx = Analyst, date_from: date | None = None, date_to: date | None = None,
             campaign_id: list[uuid.UUID] | None = Query(None)):
    start, end, t0, t1 = _bounds(date_from, date_to)
    companies = ctx.db.scalar(sa.select(sa.func.count()).select_from(Company).where(Company.deleted_at.is_(None)))
    contacts = ctx.db.scalar(sa.select(sa.func.count()).select_from(Contact).where(Contact.deleted_at.is_(None)))
    eligible = ctx.db.scalar(sa.select(sa.func.count()).select_from(Contact).where(eligibility_clause()))
    camp_q = sa.select(sa.func.count()).select_from(Campaign).where(Campaign.deleted_at.is_(None))
    total_campaigns = ctx.db.scalar(camp_q)
    sent_campaigns = ctx.db.scalar(camp_q.where(Campaign.started_at >= t0, Campaign.started_at < t1))

    rec = sa.select(CampaignRecipient).where(CampaignRecipient.sent_at >= t0, CampaignRecipient.sent_at < t1)
    if campaign_id:
        rec = rec.where(CampaignRecipient.campaign_id.in_(campaign_id))
    r = rec.subquery()
    row = ctx.db.execute(sa.select(
        sa.func.count(),
        sa.func.count().filter(r.c.status.in_([RecipientStatus.DELIVERED, RecipientStatus.COMPLAINED])),
        sa.func.count().filter(r.c.status == RecipientStatus.BOUNCED),
        sa.func.count().filter(r.c.first_opened_at.isnot(None)),
        sa.func.count().filter(r.c.first_clicked_at.isnot(None)),
        sa.func.count().filter(r.c.status == RecipientStatus.COMPLAINED),
    ).select_from(r)).one()
    sent, delivered, bounced, opened, clicked, complained = row
    unsub = ctx.db.scalar(sa.select(sa.func.count(sa.distinct(EmailEvent.recipient_id))).where(
        EmailEvent.event_type == EventType.UNSUBSCRIBE, EmailEvent.recipient_id.in_(sa.select(r.c.id))))
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "total_companies": companies, "total_contacts": contacts, "eligible_subscribers": eligible,
        "total_campaigns": total_campaigns, "campaigns_sent_in_period": sent_campaigns,
        "emails_sent": sent, "emails_delivered": delivered, "bounces": bounced, "complaints": complained,
        "unique_opens": opened, "unique_clicks": clicked, "unsubscribes": unsub,
        "delivery_rate": an.pct(delivered, sent), "bounce_rate": an.pct(bounced, sent),
        "open_rate": an.pct(opened, sent), "click_rate": an.pct(clicked, sent),
        "click_to_open_rate": an.pct(clicked, opened), "unsubscribe_rate": an.pct(unsub, sent),
        "complaint_rate": an.pct(complained, sent),
    }


@router.get("/trends")
def trends(ctx: Ctx = Analyst, date_from: date | None = None, date_to: date | None = None,
           campaign_id: list[uuid.UUID] | None = Query(None), interval: str = Query("day", pattern="^(day|week|month)$")):
    start, end, _, _ = _bounds(date_from, date_to)
    bucket = sa.func.date_trunc(interval, CampaignDailyStat.day).label("bucket")
    q = (sa.select(bucket, *[sa.func.sum(getattr(CampaignDailyStat, f)).label(f) for f in
                             ("sent", "delivered", "bounced", "opened", "unique_opened", "clicked", "unique_clicked",
                              "unsubscribed", "complained")])
         .where(CampaignDailyStat.day >= start, CampaignDailyStat.day <= end).group_by(bucket).order_by(bucket))
    if campaign_id:
        q = q.where(CampaignDailyStat.campaign_id.in_(campaign_id))
    rows = {r.bucket.date(): r for r in ctx.db.execute(q)}
    out, d = [], start
    step = {"day": timedelta(days=1), "week": timedelta(days=7), "month": None}[interval]
    if interval == "week":
        d = start - timedelta(days=start.weekday())
    if interval == "month":
        d = start.replace(day=1)
    while d <= end:
        r = rows.get(d)
        vals = {f: int(getattr(r, f) or 0) if r else 0 for f in
                ("sent", "delivered", "bounced", "opened", "unique_opened", "clicked", "unique_clicked",
                 "unsubscribed", "complained")}
        out.append({"date": d.isoformat(), **vals, "open_rate": an.pct(vals["unique_opened"], vals["sent"]),
                    "click_rate": an.pct(vals["unique_clicked"], vals["sent"])})
        d = (d.replace(year=d.year + (d.month // 12), month=d.month % 12 + 1) if interval == "month" else d + step)
    return out


@router.get("/campaigns")
def campaign_table(ctx: Ctx = Analyst, date_from: date | None = None, date_to: date | None = None,
                   campaign_id: list[uuid.UUID] | None = Query(None), limit: int = Query(50, le=500)):
    _, _, t0, t1 = _bounds(date_from, date_to)
    q = (sa.select(Campaign).where(Campaign.deleted_at.is_(None), Campaign.started_at.isnot(None),
                                   Campaign.started_at >= t0, Campaign.started_at < t1)
         .order_by(Campaign.started_at.desc()).limit(limit))
    if campaign_id:
        q = q.where(Campaign.id.in_(campaign_id))
    return [{"id": str(c.id), "name": c.name, "status": c.status.value, "started_at": c.started_at,
             "completed_at": c.completed_at, **an.campaign_stats(ctx.db, c.id)} for c in ctx.db.scalars(q)]


@router.get("/delivery")
def delivery(ctx: Ctx = Analyst, date_from: date | None = None, date_to: date | None = None,
             campaign_id: list[uuid.UUID] | None = Query(None)):
    _, _, t0, t1 = _bounds(date_from, date_to)
    q = (sa.select(CampaignRecipient.status, sa.func.count()).where(
        CampaignRecipient.created_at >= t0, CampaignRecipient.created_at < t1).group_by(CampaignRecipient.status))
    if campaign_id:
        q = q.where(CampaignRecipient.campaign_id.in_(campaign_id))
    rows = dict(ctx.db.execute(q).all())
    return [{"status": s.value, "count": rows.get(s, 0)} for s in RecipientStatus]


@router.get("/audience-growth")
def audience_growth(ctx: Ctx = Analyst, date_from: date | None = None, date_to: date | None = None):
    start, end, t0, t1 = _bounds(date_from, date_to)
    day = sa.func.date_trunc("day", Contact.created_at).label("d")
    added = dict((r.d.date(), r.n) for r in ctx.db.execute(
        sa.select(day, sa.func.count().label("n")).where(Contact.created_at >= t0, Contact.created_at < t1)
        .group_by(day)))
    cday = sa.func.date_trunc("day", ConsentRecord.granted_at).label("d")
    consents = dict((r.d.date(), r.n) for r in ctx.db.execute(
        sa.select(cday, sa.func.count(sa.distinct(ConsentRecord.contact_id)).label("n"))
        .where(ConsentRecord.granted_at >= t0, ConsentRecord.granted_at < t1).group_by(cday)))
    eday = sa.func.date_trunc("day", EmailEvent.occurred_at).label("d")
    unsubs = dict((r.d.date(), r.n) for r in ctx.db.execute(
        sa.select(eday, sa.func.count().label("n")).where(EmailEvent.event_type == EventType.UNSUBSCRIBE,
                                                          EmailEvent.occurred_at >= t0, EmailEvent.occurred_at < t1)
        .group_by(eday)))
    running = ctx.db.scalar(sa.select(sa.func.count()).select_from(Contact).where(Contact.created_at < t0)) or 0
    out, d = [], start
    while d <= end:
        running += added.get(d, 0)
        out.append({"date": d.isoformat(), "contacts_added": added.get(d, 0), "total_contacts": running,
                    "consents_recorded": consents.get(d, 0), "unsubscribes": unsubs.get(d, 0)})
        d += timedelta(days=1)
    return out


@router.get("/distribution")
def distribution(ctx: Ctx = Analyst, by: str = Query("industry", pattern="^(industry|country|city|company_size|"
                                                                      "subscription_status|department)$"),
                 eligible_only: bool = False, limit: int = Query(15, le=100)):
    base = (sa.select(Contact.id).join(Company, Company.id == Contact.company_id)
            .where(Contact.deleted_at.is_(None), Company.deleted_at.is_(None)))
    if eligible_only:
        base = base.where(eligibility_clause())
    if by == "industry":
        key = sa.func.coalesce(Industry.name, "Unspecified")
        q = base.outerjoin(Industry, Industry.id == Company.industry_id)
    elif by == "country":
        key, q = sa.func.coalesce(Contact.country_code, Company.country_code, "Unspecified"), base
    elif by == "city":
        key, q = sa.func.coalesce(Contact.city, Company.city, "Unspecified"), base
    elif by == "company_size":
        key, q = sa.func.coalesce(sa.cast(Company.company_size, sa.Text), "Unspecified"), base
    elif by == "department":
        key, q = sa.func.coalesce(Contact.department, "Unspecified"), base
    else:
        key, q = sa.cast(Contact.subscription_status, sa.Text), base
    q = q.with_only_columns(key.label("k"), sa.func.count().label("n")).group_by(sa.text("1")).order_by(
        sa.desc("n"))
    rows = ctx.db.execute(q).all()
    top, rest = rows[:limit], rows[limit:]
    out = [{"label": k, "count": n} for k, n in top]
    if rest:
        out.append({"label": "Other", "count": sum(n for _, n in rest)})
    total = sum(x["count"] for x in out)
    for x in out:
        x["share"] = an.pct(x["count"], total)
    return out


@router.get("/campaign-options")
def campaign_options(ctx: Ctx = Analyst):
    return [{"id": str(i), "name": n} for i, n in ctx.db.execute(
        sa.select(Campaign.id, Campaign.name).where(Campaign.started_at.isnot(None), Campaign.deleted_at.is_(None))
        .order_by(Campaign.started_at.desc()).limit(200))]


