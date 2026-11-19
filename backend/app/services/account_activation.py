"""Consume an account invitation and set the initial password atomically."""

import re
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.passwords import hash_new_password
from app.models.enums import AccountActionPurpose, AccountStatus
from app.models.user import AccountActionToken, User
from app.schemas.auth import ActivationRequest

_INVITATION_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}")


class InvalidActivationError(Exception):
    pass


class ActivationStoreError(RuntimeError):
    pass


def _valid_token(digest: bytes, now: datetime):
    return (
        AccountActionToken.token_digest == digest,
        AccountActionToken.purpose == AccountActionPurpose.ACTIVATION,
        AccountActionToken.created_at <= now,
        AccountActionToken.expires_at > now,
        AccountActionToken.consumed_at.is_(None),
        AccountActionToken.invalidated_at.is_(None),
    )


def activate_account(sessions: sessionmaker[Session], request: ActivationRequest) -> None:
    raw = request.invitation.get_secret_value()
    if not _INVITATION_FORMAT.fullmatch(raw):
        raise InvalidActivationError()
    digest = sha256(raw.encode("ascii")).digest()

    try:
        with sessions() as db:
            owner = db.scalar(
                select(AccountActionToken.user_id).join(AccountActionToken.user).where(
                    *_valid_token(digest, datetime.now(timezone.utc)),
                    User.account_status == AccountStatus.PENDING_ACTIVATION,
                    AccountActionToken.auth_version == User.auth_version,
                )
            )
        if owner is None:
            raise InvalidActivationError()

        password_hash = hash_new_password(request.password.get_secret_value())
        with sessions.begin() as db:
            # Account mutations lock the user before credentials owned by that user.
            user = db.scalar(select(User).where(User.id == owner).with_for_update())
            if user is None or user.account_status != AccountStatus.PENDING_ACTIVATION:
                raise InvalidActivationError()
            now = datetime.now(timezone.utc)
            token = db.scalar(
                select(AccountActionToken).where(
                    *_valid_token(digest, now),
                    AccountActionToken.user_id == user.id,
                    AccountActionToken.auth_version == user.auth_version,
                ).with_for_update()
            )
            if token is None:
                raise InvalidActivationError()
            token.consumed_at = now
            user.hashed_password = password_hash
            user.account_status = AccountStatus.ACTIVE
            user.auth_version += 1
    except SQLAlchemyError:
        raise ActivationStoreError("Account activation could not be saved.") from None
