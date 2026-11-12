"""v1 API router. Module routers are registered here as each phase lands."""
from fastapi import APIRouter

api_router = APIRouter()


@api_router.get("/meta", tags=["meta"])
def meta() -> dict[str, list[str]]:
    """Lists implemented modules so the frontend can feature-flag navigation."""
    return {"modules": []}
