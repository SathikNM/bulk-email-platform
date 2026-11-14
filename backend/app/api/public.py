"""Public (unauthenticated) endpoints: hosted images. Tracking/unsubscribe/webhooks are added in Phase 8."""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from app.core.config import settings

router = APIRouter(include_in_schema=True, tags=["public"])
MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


@router.get("/assets/{key:path}")
def asset(key: str):
    if settings.STORAGE_BACKEND != "local" or ".." in key or "/images/" not in key:
        return Response(status_code=404)
    base = Path(settings.LOCAL_STORAGE_DIR).resolve()
    path = (base / key).resolve()
    if base not in path.parents or not path.is_file() or path.suffix.lower() not in MEDIA:
        return Response(status_code=404)
    return FileResponse(path, media_type=MEDIA[path.suffix.lower()],
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
