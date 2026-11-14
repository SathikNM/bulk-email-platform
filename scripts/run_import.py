"""Server-side contact import (used by scripts/run-import.cmd).

Reads /tmp/import.xlsx inside the API container, imports it into the first workspace with the platform's
normal import engine (same validation, de-duplication, suppression and consent rules as the web import),
then gives every imported contact's company the same category as the contact.
"""
import os
import uuid

import sqlalchemy as sa

from app.db.session import system_scope, worker_session
from app.models import Category, Company, Contact, ImportJob, User, Workspace
from app.models.enums import CategoryScope, ImportEntity
from app.services import imports, storage

path = os.environ.get("IMPORT_FILE", "/tmp/import.xlsx")
data = open(path, "rb").read()
fname = os.path.basename(path)
with system_scope() as s:
    ws = s.scalar(sa.select(Workspace).order_by(Workspace.created_at))
    user = s.scalar(sa.select(User).order_by(User.is_superadmin.desc(), User.created_at))
    ws_id, user_id = ws.id, user.id
print("workspace:", ws.name)

headers, _ = imports.read_rows(data, fname)
mapping = imports.suggest_mapping(headers, ImportEntity.CONTACT)
print("mapping:", mapping)
key = f"{ws_id}/imports/{uuid.uuid4().hex}_{fname}"
storage.put(key, data)

db = worker_session(ws_id)
try:
    job = ImportJob(workspace_id=ws_id, entity=ImportEntity.CONTACT, file_key=key, original_filename=fname,
                    column_mapping=mapping, options={"update_existing": True, "create_missing_taxonomy": True},
                    created_by=user_id)
    db.add(job)
    db.commit()
    imports.run_job(db, job)
    db.refresh(job)
    print(f"status={job.status.value} total={job.total_rows} inserted={job.inserted} updated={job.updated} "
          f"skipped={job.skipped}")
    for e in (job.errors or [])[:50]:
        print("  row", e.get("row"), ":", e.get("error"))

    # Company category = contact category (e.g. "Small Companies")
    pairs = db.execute(sa.select(Contact.company_id, Category.name).join(Category, Category.id == Contact.category_id)
                       .where(Contact.deleted_at.is_(None))).all()
    names = {n for _, n in pairs}
    comp_cats = {}
    for n in names:
        c = db.scalar(sa.select(Category).where(Category.scope == CategoryScope.COMPANY, Category.name == n))
        if c is None:
            c = Category(workspace_id=ws_id, scope=CategoryScope.COMPANY, name=n)
            db.add(c)
            db.flush()
        comp_cats[n] = c.id
    for company_id, n in pairs:
        db.execute(sa.text("INSERT INTO company_categories (company_id, category_id) VALUES (:a, :b) "
                           "ON CONFLICT DO NOTHING"), {"a": company_id, "b": comp_cats[n]})
    db.commit()
    print("companies:", db.scalar(sa.select(sa.func.count()).select_from(Company)),
          "| with Arabic name:", db.scalar(sa.select(sa.func.count()).select_from(Company).where(Company.name_ar.is_not(None))),
          "| contacts:", db.scalar(sa.select(sa.func.count()).select_from(Contact).where(Contact.deleted_at.is_(None))))
finally:
    db.close()
print("DONE")
