"""Enqueue Celery tasks only after the current DB transaction commits.

Prevents workers from racing ahead of uncommitted rows (and makes eager mode in tests
behave like production).
"""
from sqlalchemy import event
from sqlalchemy.orm import Session

_KEY = "bep_after_commit"


def enqueue_after_commit(db: Session, task, *args, **kwargs) -> None:
    db.info.setdefault(_KEY, []).append((task, args, kwargs))


@event.listens_for(Session, "after_commit")
def _run(session: Session) -> None:
    pending = session.info.pop(_KEY, [])
    for task, args, kwargs in pending:
        task.delay(*args, **kwargs)


@event.listens_for(Session, "after_rollback")
def _drop(session: Session) -> None:
    session.info.pop(_KEY, None)
