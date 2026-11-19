"""Transactional authentication sessions and opaque refresh-token rotation."""

import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from sqlalchemy import Row, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database.session import get_session_factory
from app.models.enums import AccountStatus
from app.models.user import AuthSession, RefreshToken, User

_REFRESH_TOKEN_BYTES = 32
_REFRESH_TOKEN_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")


class InvalidSessionError(Exception):
    """Authentication cannot continue with the supplied session or token."""

    def __init__(self):
        super().__init__("Invalid authentication session.")


class SessionStoreError(RuntimeError):
    """A session database operation failed without exposing query details."""


@dataclass(frozen=True)
class SessionCredentials:
    session_id: UUID
    user_id: UUID
    session_expires_at: datetime
    refresh_expires_at: datetime
    refresh_token: str = field(repr=False)


def _utc_now() -> datetime:
    # The existing database columns store naive UTC timestamps.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def _session_is_active(session: AuthSession | None, now: datetime) -> bool:
    return session is not None and session.revoked_at is None and session.created_at <= now < session.expires_at


def _lock_user(
    db: Session, user_id: UUID, expected_password_hash: str | None = None, expected_auth_version: int | None = None,
) -> bool | None:
    # When both rows are needed, lock the user before the session.
    statement = select(User.account_status == AccountStatus.ACTIVE).where(User.id == user_id)
    if expected_password_hash is not None:
        statement = statement.where(User.hashed_password == expected_password_hash)
    if expected_auth_version is not None:
        statement = statement.where(User.auth_version == expected_auth_version)
    return db.scalar(statement.with_for_update(read=True))


def _lock_session(db: Session, session_id: UUID, user_id: UUID) -> AuthSession | None:
    return db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        .with_for_update()
    )


def _refresh_token_owner(db: Session, digest: str) -> Row[tuple[UUID, UUID]] | None:
    # Locate the session without caching token state before taking its lock.
    return db.execute(
        select(RefreshToken.session_id, RefreshToken.user_id).where(RefreshToken.token_hash == digest)
    ).one_or_none()


def _read_refresh_token(db: Session, digest: str, session_id: UUID, user_id: UUID) -> RefreshToken | None:
    return db.scalar(select(RefreshToken).where(
        RefreshToken.token_hash == digest,
        RefreshToken.session_id == session_id,
        RefreshToken.user_id == user_id,
    ))


class AuthSessionService:
    """Owns transaction boundaries. Call without an enclosing request transaction."""

    def __init__(
        self,
        *,
        session_lifetime: timedelta,
        refresh_lifetime: timedelta,
        session_factory: sessionmaker[Session] | None = None,
    ):
        if session_lifetime <= timedelta(0) or refresh_lifetime <= timedelta(0):
            raise ValueError("Session and refresh-token lifetimes must be positive.")
        self._session_lifetime = session_lifetime
        self._refresh_lifetime = refresh_lifetime
        self._sessions = session_factory if session_factory is not None else get_session_factory()

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as db:
                # The token re-read after locking must see the previous transaction's commit.
                db.connection(execution_options={"isolation_level": "READ COMMITTED"})
                yield db
        except SQLAlchemyError:
            raise SessionStoreError("Authentication session storage failed.") from None

    def create_session(
        self,
        user_id: UUID,
        *,
        session_id: UUID | None = None,
        expected_password_hash: str | None = None,
        expected_auth_version: int | None = None,
    ) -> SessionCredentials:
        """Issue credentials after the caller has authenticated the user."""
        with self._transaction() as db:
            if not _lock_user(db, user_id, expected_password_hash, expected_auth_version):
                raise InvalidSessionError()

            now = _utc_now()
            session = AuthSession(
                id=session_id, user_id=user_id, created_at=now, expires_at=now + self._session_lifetime,
            )
            db.add(session)
            db.flush()
            return self._issue_token(db, session, now)

    def rotate_refresh_token(
        self, refresh_token: str, *, expected_user_id: UUID | None = None
    ) -> SessionCredentials:
        """Rotate an opaque token or revoke its session on detected replay."""
        if not isinstance(refresh_token, str) or not _REFRESH_TOKEN_FORMAT.fullmatch(refresh_token):
            raise InvalidSessionError()
        digest = _token_hash(refresh_token)

        with self._transaction() as db:
            owner = _refresh_token_owner(db, digest)
            if owner is None:
                raise InvalidSessionError()
            session_id, user_id = owner
            if expected_user_id is not None and expected_user_id != user_id:
                raise InvalidSessionError()

            user_active = _lock_user(db, user_id)
            session = _lock_session(db, session_id, user_id)
            if session is None or session.revoked_at is not None:
                raise InvalidSessionError()

            token = _read_refresh_token(db, digest, session_id, user_id)
            now = _utc_now()
            if token is None or not _session_is_active(session, now):
                raise InvalidSessionError()

            if token.consumed_at is not None:
                self._revoke_locked_session(db, session, now)
            else:
                if not user_active or token.is_revoked or not token.created_at <= now < token.expires_at:
                    raise InvalidSessionError()

                token.consumed_at = now
                token.is_revoked = True
                # Release the partial unique-index slot before inserting the replacement.
                db.flush()
                return self._issue_token(db, session, now)

        # Raising inside the transaction would roll back replay-triggered revocation.
        raise InvalidSessionError()

    def revoke_by_refresh_token(self, refresh_token: str) -> None:
        """Revoke the session named by a valid token or a known replay."""
        if not isinstance(refresh_token, str) or not _REFRESH_TOKEN_FORMAT.fullmatch(refresh_token):
            return
        digest = _token_hash(refresh_token)

        with self._transaction() as db:
            owner = _refresh_token_owner(db, digest)
            if owner is None:
                return
            session_id, user_id = owner
            session = _lock_session(db, session_id, user_id)
            token = _read_refresh_token(db, digest, session_id, user_id)
            now = _utc_now()
            if token is None or not _session_is_active(session, now):
                return

            if token.consumed_at is not None or (
                not token.is_revoked and token.created_at <= now < token.expires_at
            ):
                self._revoke_locked_session(db, session, now)

    def revoke_session(self, session_id: UUID, *, user_id: UUID) -> bool:
        """Revoke the user's session. Repeating logout for that session is safe."""
        with self._transaction() as db:
            session = _lock_session(db, session_id, user_id)
            if session is None:
                return False
            if session.revoked_at is None:
                self._revoke_locked_session(db, session, _utc_now())
            return True

    def is_session_active(self, session_id: UUID, *, user_id: UUID) -> bool:
        with self._transaction() as db:
            session = db.scalar(
                select(AuthSession)
                .join(AuthSession.user)
                .where(AuthSession.id == session_id, AuthSession.user_id == user_id,
                       User.account_status == AccountStatus.ACTIVE)
            )
            return _session_is_active(session, _utc_now())

    def _issue_token(self, db: Session, session: AuthSession, now: datetime) -> SessionCredentials:
        token = secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)
        expires_at = min(now + self._refresh_lifetime, session.expires_at)
        db.add(RefreshToken(
            user_id=session.user_id,
            session_id=session.id,
            token_hash=_token_hash(token),
            created_at=now,
            expires_at=expires_at,
        ))
        return SessionCredentials(session.id, session.user_id, session.expires_at, expires_at, token)

    @staticmethod
    def _revoke_locked_session(db: Session, session: AuthSession, now: datetime) -> None:
        session.revoked_at = max(now, session.created_at)
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.session_id == session.id,
                RefreshToken.user_id == session.user_id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )
