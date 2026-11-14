"""v1 API router."""
from fastapi import APIRouter

from app.api.v1 import auth, companies, imports, taxonomy, workspaces

api_router = APIRouter()
for module in (auth, workspaces, taxonomy, companies, imports):
    api_router.include_router(module.router)

MODULES = ["auth", "workspaces", "taxonomy", "companies", "imports"]


@api_router.get("/meta", tags=["meta"])
def meta() -> dict[str, list[str]]:
    """Lists implemented modules so the frontend can feature-flag navigation."""
    return {"modules": MODULES}
