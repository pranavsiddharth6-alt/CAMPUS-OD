"""Issue and verify signed access tokens for Campus OD."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidKeyError, PyJWTError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings

_ALGORITHM = "HS256"
_TOKEN_TYPE = "at+jwt"
_MAX_TOKEN_LENGTH = 4096
_JWT_FORMAT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class JWTConfigurationError(RuntimeError):
    """Access-token signing or verification is unavailable."""


class InvalidAccessTokenError(Exception):
    def __init__(self):
        super().__init__("Invalid access token.")


class AccessTokenClaims(BaseModel):
    """Verified identity claims. Authorization still requires checking the database."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    sub: UUID
    sid: UUID
    iss: str
    aud: str
    iat: Annotated[int, Field(strict=True, gt=0)]
    nbf: Annotated[int, Field(strict=True, gt=0)]
    exp: Annotated[int, Field(strict=True, gt=0)]
    jti: UUID


@dataclass(frozen=True)
class _AccessTokenConfig:
    issuer: str
    audience: str
    lifetime_minutes: int
    key: bytes = field(repr=False)


def _validate_identifier(value: str | None, setting: str) -> str:
    if not value or len(value) > 255 or not value.isascii() or not value.isprintable() or " " in value:
        raise JWTConfigurationError(f"{setting} must be a non-empty ASCII identifier without whitespace.")
    return value


def _access_token_config() -> _AccessTokenConfig:
    if settings.JWT_ALGORITHM != _ALGORITHM:
        raise JWTConfigurationError("JWT_ALGORITHM must be HS256.")

    configured_secret = settings.JWT_SIGNING_SECRET
    if configured_secret is None:
        raise JWTConfigurationError("JWT_SIGNING_SECRET is required.")
    secret = configured_secret.get_secret_value()
    try:
        key = secret.encode("utf-8")
    except UnicodeEncodeError:
        raise JWTConfigurationError("JWT_SIGNING_SECRET must be valid UTF-8.") from None
    if len(key) < 32 or not secret.strip():
        raise JWTConfigurationError("JWT_SIGNING_SECRET must contain at least 32 bytes of key material.")

    lifetime = str(settings.JWT_ACCESS_TOKEN_MINUTES)
    if not re.fullmatch(r"[0-9]{1,2}", lifetime) or not 1 <= int(lifetime) <= 60:
        raise JWTConfigurationError("JWT_ACCESS_TOKEN_MINUTES must be an integer from 1 to 60.")

    return _AccessTokenConfig(
        issuer=_validate_identifier(settings.JWT_ISSUER, "JWT_ISSUER"),
        audience=_validate_identifier(settings.JWT_AUDIENCE, "JWT_AUDIENCE"),
        lifetime_minutes=int(lifetime),
        key=key,
    )


def create_access_token(user_id: UUID, session_id: UUID) -> str:
    """Create an access token for a trusted caller's user and session IDs."""
    config = _access_token_config()
    now = int(datetime.now(timezone.utc).timestamp())
    try:
        claims = AccessTokenClaims(
            sub=user_id, sid=session_id, iss=config.issuer, aud=config.audience,
            iat=now, nbf=now, exp=now + config.lifetime_minutes * 60, jti=uuid4(),
        )
    except ValidationError:
        raise InvalidAccessTokenError() from None
    try:
        return jwt.encode(
            claims.model_dump(mode="json"), config.key, algorithm=_ALGORITHM, headers={"typ": _TOKEN_TYPE}
        )
    except PyJWTError:
        raise JWTConfigurationError("Access-token signing is unavailable.") from None


def verify_access_token(encoded_token: str) -> AccessTokenClaims:
    """Validate the signature and claims before returning the token's identity."""
    config = _access_token_config()
    if (
        not isinstance(encoded_token, str)
        or len(encoded_token) > _MAX_TOKEN_LENGTH
        or not _JWT_FORMAT.fullmatch(encoded_token)
    ):
        raise InvalidAccessTokenError()

    try:
        verified = jwt.decode_complete(
            encoded_token, config.key, algorithms=[_ALGORITHM],
            issuer=config.issuer, audience=config.audience,
            options={"require": list(AccessTokenClaims.model_fields), "strict_aud": True},
        )
        claims = AccessTokenClaims.model_validate(verified["payload"])
    except InvalidKeyError:
        raise JWTConfigurationError("Access-token verification is unavailable.") from None
    except (PyJWTError, ValueError, TypeError, OverflowError, RecursionError):
        raise InvalidAccessTokenError() from None

    if verified["header"].get("typ") != _TOKEN_TYPE or not claims.iat <= claims.nbf < claims.exp:
        raise InvalidAccessTokenError()
    return claims
