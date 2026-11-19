"""Authenticate Campus OD users and enforce route-level role requirements."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.access_tokens import InvalidAccessTokenError, JWTConfigurationError, verify_access_token
from app.database.session import get_session_factory
from app.models.enums import AccountStatus, UserRole
from app.models.user import AuthSession, User

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user_id: UUID
    session_id: UUID
    role: UserRole
    email: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials.",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthenticatedUser:
    """Validate the access token and load a current, session-bound identity."""
    if credentials is None:
        raise _unauthorized()

    try:
        claims = verify_access_token(credentials.credentials)
    except (InvalidAccessTokenError, JWTConfigurationError):
        raise _unauthorized() from None

    statement = (
        select(User.id.label("user_id"), AuthSession.id.label("session_id"), User.role, User.email,
               AuthSession.created_at, AuthSession.expires_at)
        .select_from(AuthSession)
        .join(AuthSession.user)
        .where(
            User.id == claims.sub,
            User.account_status == AccountStatus.ACTIVE,
            AuthSession.id == claims.sid,
            AuthSession.revoked_at.is_(None),
        )
    )

    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            identity = db.execute(statement).one_or_none()
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        raise _unauthorized() from None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if identity is None or not identity.created_at <= now < identity.expires_at:
        raise _unauthorized()

    return AuthenticatedUser(
        user_id=identity.user_id, session_id=identity.session_id, role=identity.role, email=identity.email,
    )


def require_roles(role: UserRole, *additional_roles: UserRole) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    """Build a dependency allowing any of the server-configured roles."""
    allowed_roles = frozenset((role, *additional_roles))

    def check_role(user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions.",
                headers={"Cache-Control": "no-store"},
            )
        return user

    return check_role
