"""v1 API router."""
from fastapi import APIRouter

from app.api.v1 import auth, companies, contacts, imports, segments, suppressions, taxonomy, workspaces

api_router = APIRouter()
for module in (auth, workspaces, taxonomy, companies, contacts, imports, suppressions, segments):
    api_router.include_router(module.router)

MODULES = ["auth", "workspaces", "taxonomy", "companies", "contacts", "imports", "suppressions", "segments"]


@api_router.get("/meta", tags=["meta"])
def meta() -> dict[str, list[str]]:
    """Lists implemented modules so the frontend can feature-flag navigation."""
    return {"modules": MODULES}
