"""Origin validation for requests that set or use authentication cookies."""

from fastapi import HTTPException, Request, status

from app.core.config import settings


async def require_trusted_auth_origin(request: Request) -> None:
    origins = request.headers.getlist("origin")
    allowed = settings.CORS_ORIGINS
    if (
        len(origins) != 1
        or not origins[0].startswith(("https://", "http://"))
        or not isinstance(allowed, list)
        or origins[0] not in allowed
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Request origin is not allowed.", headers={"Cache-Control": "no-store"},
        )
