"""Authentication endpoints for college-provisioned accounts."""

import json
import secrets
from datetime import timedelta, timezone
from functools import lru_cache
from hashlib import sha256
from math import ceil
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Annotated, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app.core.access_tokens import InvalidAccessTokenError, create_access_token
from app.core.config import settings
from app.core.passwords import hash_password, verify_password
from app.database.session import get_session_factory
from app.dependencies.auth import AuthenticatedUser, get_current_user
from app.dependencies.auth_origin import require_trusted_auth_origin
from app.models.enums import AccountStatus
from app.models.user import User
from app.schemas.auth import AccessTokenResponse, ActivationRequest, CurrentUserResponse, LoginRequest, LoginResponse
from app.services.account_activation import InvalidActivationError, activate_account
from app.services.auth_sessions import AuthSessionService, InvalidSessionError, SessionCredentials

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])
_REFRESH_COOKIE = "__Secure-campus_od_refresh"
_AUTH_COOKIE_PATH = "/api/v1/auth"
_CSRF_HEADER = "X-CSRF-Protection"
_CSRF_OPENAPI = {"parameters": [{
    "name": _CSRF_HEADER,
    "in": "header",
    "required": True,
    "schema": {"type": "string", "enum": ["1"]},
}]}
_MAX_LOGIN_BODY_BYTES = 8192
_WINDOW_SECONDS = 60
_PER_ACCOUNT_LIMIT = 5
_PER_IP_LIMIT = 30
_PER_WORKER_LIMIT = 300
_NO_STORE = {"Cache-Control": "no-store"}
_AUTH_UNAVAILABLE = "Authentication is unavailable."
_INVALID_CREDENTIALS = "Invalid authentication credentials."
_RequestModel = TypeVar("_RequestModel", bound=BaseModel)


def _unauthorized() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password.", headers=_NO_STORE)


def _session_service(session_factory: sessionmaker[Session]) -> AuthSessionService:
    return AuthSessionService(
        session_factory=session_factory,
        session_lifetime=timedelta(minutes=settings.AUTH_SESSION_LIFETIME_MINUTES),
        refresh_lifetime=timedelta(minutes=settings.AUTH_REFRESH_TOKEN_LIFETIME_MINUTES),
    )


def _set_refresh_cookie(response: Response, session: SessionCredentials) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=session.refresh_token,
        expires=session.refresh_expires_at.replace(tzinfo=timezone.utc),
        path=_AUTH_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE, path=_AUTH_COOKIE_PATH, secure=True, httponly=True, samesite="lax",
    )


def _refresh_error(status_code: int, detail: str, *, clear_cookie: bool = False) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail}, headers=_NO_STORE)
    if clear_cookie:
        _clear_refresh_cookie(response)
    return response


async def _require_auth_csrf(request: Request) -> None:
    # A browser must preflight this header on cross-origin requests.
    if request.headers.getlist(_CSRF_HEADER) != ["1"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF protection check failed.", headers=_NO_STORE)


_COOKIE_AUTH_GUARDS = [Depends(require_trusted_auth_origin), Depends(_require_auth_csrf)]


def _rate_limited(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many login attempts. Try again later.",
        headers={**_NO_STORE, "Retry-After": str(retry_after)},
    )


class _LoginRateLimit:
    """Fixed window with bounded state. Entries are capped by the per-worker limit."""

    def __init__(self):
        self._lock = Lock()
        self._reset_at = 0.0
        self._attempts = 0
        self._clients: dict[str, int] = {}
        self._accounts: dict[bytes, int] = {}

    def record_attempt(self, client: str, email: str | None) -> None:
        account = sha256(email.encode("utf-8")).digest() if email is not None else None
        with self._lock:
            now = monotonic()
            if now >= self._reset_at:
                self._reset_at = now + _WINDOW_SECONDS
                self._attempts = 0
                self._clients.clear()
                self._accounts.clear()

            retry_after = max(1, ceil(self._reset_at - now))
            client_attempts = self._clients.get(client, 0)
            if client_attempts >= _PER_IP_LIMIT or self._attempts >= _PER_WORKER_LIMIT:
                raise _rate_limited(retry_after)

            self._attempts += 1
            self._clients[client] = client_attempts + 1
            if account is not None:
                account_attempts = self._accounts.get(account, 0)
                if account_attempts >= _PER_ACCOUNT_LIMIT:
                    raise _rate_limited(retry_after)
                self._accounts[account] = account_attempts + 1


_rate_limit = _LoginRateLimit()
_activation_rate_limit = _LoginRateLimit()
# Reserve a slot before submitting work to the shared thread pool.
_login_slots = BoundedSemaphore(value=2)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(32))


async def read_auth_json(request: Request, schema: type[_RequestModel]) -> _RequestModel | None:
    content_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Expected a JSON request.", headers=_NO_STORE)

    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > _MAX_LOGIN_BODY_BYTES:
                raise HTTPException(413, "Authentication request is too large.", headers=_NO_STORE)
            body.extend(chunk)
        return schema.model_validate(json.loads(body))
    except (ClientDisconnect, ValueError, RecursionError):
        # FastAPI's default request validation response can include raw input.
        return None


def _authenticate_login(credentials: LoginRequest) -> tuple[LoginResponse, SessionCredentials]:
    try:
        session_factory = get_session_factory()
        with session_factory() as db:
            user = db.execute(
                select(User.id, User.hashed_password, User.account_status, User.auth_version)
                .where(User.email == credentials.email)
            ).one_or_none()

        dummy_hash = _dummy_password_hash()
        stored_hash = user.hashed_password if user is not None else None
        matches = verify_password(
            credentials.password.get_secret_value(), stored_hash if stored_hash is not None else dummy_hash,
        )
        if user is None or user.account_status != AccountStatus.ACTIVE or stored_hash is None or not matches:
            raise _unauthorized()

        # Validate signing before creating persistent credentials. The JWT is sent only after the commit.
        session_id = uuid4()
        access = LoginResponse(access_token=create_access_token(user.id, session_id))
        service = _session_service(session_factory)
        session = service.create_session(
            user.id, session_id=session_id, expected_password_hash=stored_hash,
            expected_auth_version=user.auth_version,
        )
    except InvalidSessionError:
        raise _unauthorized() from None
    except (SQLAlchemyError, OSError, ValueError, OverflowError, RuntimeError):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, _AUTH_UNAVAILABLE, headers=_NO_STORE,
        ) from None

    return access, session


@auth_router.post(
    "/login",
    response_model=LoginResponse,
    dependencies=[Depends(require_trusted_auth_origin)],
    openapi_extra={
        "requestBody": {"required": True, "content": {"application/json": {"schema": LoginRequest.model_json_schema()}}}
    },
)
async def login(request: Request, response: Response) -> LoginResponse:
    credentials = await read_auth_json(request, LoginRequest)
    # Use the peer address provided by the server. Proxy trust belongs in server configuration.
    client = request.client.host if request.client is not None else "unknown"
    _rate_limit.record_attempt(client, credentials.email if credentials is not None else None)
    if credentials is None:
        raise _unauthorized()

    if not _login_slots.acquire(blocking=False):
        raise _rate_limited(1)
    try:
        access, session = await run_in_threadpool(_authenticate_login, credentials)
    finally:
        _login_slots.release()

    response.headers["Cache-Control"] = "no-store"
    _set_refresh_cookie(response, session)
    return access


@auth_router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    dependencies=_COOKIE_AUTH_GUARDS,
    openapi_extra=_CSRF_OPENAPI,
)
def refresh(request: Request, response: Response) -> AccessTokenResponse | JSONResponse:
    refresh_token = request.cookies.get(_REFRESH_COOKIE)
    if refresh_token is None:
        return _refresh_error(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS)

    try:
        session = _session_service(get_session_factory()).rotate_refresh_token(refresh_token)
    except InvalidSessionError:
        return _refresh_error(status.HTTP_401_UNAUTHORIZED, _INVALID_CREDENTIALS, clear_cookie=True)
    except (SQLAlchemyError, OSError, ValueError, OverflowError, RuntimeError):
        return _refresh_error(status.HTTP_503_SERVICE_UNAVAILABLE, _AUTH_UNAVAILABLE)

    # Rotation has committed. If signing fails, discard the now-consumed cookie.
    try:
        access = AccessTokenResponse(access_token=create_access_token(session.user_id, session.session_id))
    except (InvalidAccessTokenError, ValueError, OverflowError, RuntimeError):
        return _refresh_error(status.HTTP_503_SERVICE_UNAVAILABLE, _AUTH_UNAVAILABLE, clear_cookie=True)

    response.headers["Cache-Control"] = "no-store"
    _set_refresh_cookie(response, session)
    return access


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_COOKIE_AUTH_GUARDS,
    openapi_extra=_CSRF_OPENAPI,
)
def logout(request: Request) -> Response:
    refresh_token = request.cookies.get(_REFRESH_COOKIE)
    if refresh_token:
        try:
            _session_service(get_session_factory()).revoke_by_refresh_token(refresh_token)
        except (SQLAlchemyError, OSError, ValueError, OverflowError, RuntimeError):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, _AUTH_UNAVAILABLE, headers=_NO_STORE,
            ) from None

    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=_NO_STORE)
    _clear_refresh_cookie(response)
    return response


def _activate(credentials: ActivationRequest) -> None:
    activate_account(get_session_factory(), credentials)


@auth_router.post(
    "/activate", status_code=status.HTTP_204_NO_CONTENT, dependencies=_COOKIE_AUTH_GUARDS, openapi_extra=_CSRF_OPENAPI,
)
async def activate(request: Request) -> Response:
    client = request.client.host if request.client is not None else "unknown"
    _activation_rate_limit.record_attempt(client, None)
    credentials = await read_auth_json(request, ActivationRequest)
    if credentials is None:
        raise HTTPException(400, "Invalid invitation or password.", headers=_NO_STORE)
    if not _login_slots.acquire(blocking=False):
        raise _rate_limited(1)
    try:
        await run_in_threadpool(_activate, credentials)
    except (InvalidActivationError, ValueError):
        raise HTTPException(400, "Invalid invitation or password.", headers=_NO_STORE) from None
    except (SQLAlchemyError, OSError, OverflowError, RuntimeError):
        raise HTTPException(503, _AUTH_UNAVAILABLE, headers=_NO_STORE) from None
    finally:
        _login_slots.release()
    return Response(status_code=204, headers=_NO_STORE)


@auth_router.get("/me", response_model=CurrentUserResponse)
def me(response: Response, user: Annotated[AuthenticatedUser, Depends(get_current_user)]) -> CurrentUserResponse:
    response.headers.update(_NO_STORE)
    return CurrentUserResponse(id=user.user_id, email=user.email, role=user.role)
