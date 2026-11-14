"""Analytics: campaign stats, daily rollups and dashboard aggregates."""
import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import CampaignRecipient, EmailEvent
from app.models.enums import EventType, RecipientStatus

SENT_STATES = [RecipientStatus.SENT, RecipientStatus.DELIVERED, RecipientStatus.BOUNCED, RecipientStatus.COMPLAINED]


def pct(a, b) -> float:
    return round(100.0 * a / b, 2) if b else 0.0


def campaign_stats(db: Session, campaign_id) -> dict:
    rs = dict(db.execute(sa.select(CampaignRecipient.status, sa.func.count())
                         .where(CampaignRecipient.campaign_id == campaign_id)
                         .group_by(CampaignRecipient.status)).all())
    total = sum(rs.values())
    sent = sum(rs.get(s, 0) for s in SENT_STATES)
    opens, clicks = db.execute(sa.select(
        sa.func.count().filter(CampaignRecipient.first_opened_at.isnot(None)),
        sa.func.count().filter(CampaignRecipient.first_clicked_at.isnot(None)),
    ).where(CampaignRecipient.campaign_id == campaign_id)).one()
    unsub = db.scalar(sa.select(sa.func.count(sa.distinct(EmailEvent.recipient_id))).where(
        EmailEvent.campaign_id == campaign_id, EmailEvent.event_type == EventType.UNSUBSCRIBE))
    delivered = rs.get(RecipientStatus.DELIVERED, 0) + rs.get(RecipientStatus.COMPLAINED, 0)
    bounced = rs.get(RecipientStatus.BOUNCED, 0)
    pending = rs.get(RecipientStatus.QUEUED, 0) + rs.get(RecipientStatus.SENDING, 0)
    return {"recipients": total, "queued": pending, "sent": sent, "delivered": delivered, "bounced": bounced,
            "failed": rs.get(RecipientStatus.FAILED, 0), "skipped": rs.get(RecipientStatus.SKIPPED_SUPPRESSED, 0),
            "complained": rs.get(RecipientStatus.COMPLAINED, 0), "unique_opens": opens, "unique_clicks": clicks,
            "unsubscribes": unsub, "open_rate": pct(opens, sent), "click_rate": pct(clicks, sent),
            "click_to_open_rate": pct(clicks, opens), "bounce_rate": pct(bounced, sent),
            "unsubscribe_rate": pct(unsub, sent), "delivery_rate": pct(delivered, sent),
            "progress": pct(total - pending, total)}


ROLLUP_SQL = sa.text("""
INSERT INTO campaign_daily_stats (campaign_id, day, workspace_id, sent, delivered, bounced, opened, unique_opened,
                                  clicked, unique_clicked, unsubscribed, complained, updated_at)
SELECT e.campaign_id, (e.occurred_at AT TIME ZONE 'UTC')::date AS day, e.workspace_id,
       count(*) FILTER (WHERE e.event_type = 'send'),
       count(*) FILTER (WHERE e.event_type = 'delivery'),
       count(*) FILTER (WHERE e.event_type = 'bounce_hard'),
       count(*) FILTER (WHERE e.event_type = 'open' AND NOT e.is_machine),
       count(DISTINCT e.recipient_id) FILTER (WHERE e.event_type = 'open' AND NOT e.is_machine),
       count(*) FILTER (WHERE e.event_type = 'click' AND NOT e.is_machine),
       count(DISTINCT e.recipient_id) FILTER (WHERE e.event_type = 'click' AND NOT e.is_machine),
       count(DISTINCT e.recipient_id) FILTER (WHERE e.event_type = 'unsubscribe'),
       count(*) FILTER (WHERE e.event_type = 'complaint'),
       now()
FROM email_events e
WHERE e.campaign_id = :cid
GROUP BY e.campaign_id, day, e.workspace_id
ON CONFLICT (campaign_id, day) DO UPDATE SET
  sent = EXCLUDED.sent, delivered = EXCLUDED.delivered, bounced = EXCLUDED.bounced, opened = EXCLUDED.opened,
  unique_opened = EXCLUDED.unique_opened, clicked = EXCLUDED.clicked, unique_clicked = EXCLUDED.unique_clicked,
  unsubscribed = EXCLUDED.unsubscribed, complained = EXCLUDED.complained, updated_at = now()
""")


def rollup_campaign(db: Session, campaign_id) -> None:
    db.execute(ROLLUP_SQL, {"cid": str(campaign_id)})


def campaigns_with_recent_events(db: Session, hours: int = 48) -> list[uuid.UUID]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return list(db.scalars(sa.select(EmailEvent.campaign_id).where(EmailEvent.occurred_at >= since,
                                                                   EmailEvent.campaign_id.isnot(None)).distinct()))


def date_range(date_from: date | None, date_to: date | None, default_days: int = 30) -> tuple[date, date]:
    end = date_to or datetime.now(timezone.utc).date()
    start = date_from or (end - timedelta(days=default_days - 1))
    if start > end:
        start, end = end, start
    return start, end
