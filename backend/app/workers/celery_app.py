"""Celery application (Redis broker). Tasks live in app.workers.tasks."""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery("bep", broker=settings.REDIS_URL, backend=settings.REDIS_URL,
                include=["app.workers.tasks"])
celery.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_routes={
        "bep.send_batch": {"queue": "send"},
        "bep.prepare_campaign": {"queue": "send"},
    },
    beat_schedule={
        "dispatch-due-campaigns": {"task": "bep.dispatch_due_campaigns", "schedule": 30.0},
        "rollup-stats": {"task": "bep.rollup_all_stats", "schedule": crontab(minute="*/5")},
        "resume-stalled-campaigns": {"task": "bep.resume_stalled", "schedule": 120.0},
    },
)
