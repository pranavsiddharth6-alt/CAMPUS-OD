"""Public request and response schemas for authentication."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.core.passwords import MAX_PASSWORD_BYTES, MIN_NEW_PASSWORD_LENGTH
from app.models.enums import UserRole


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    # Use the same address normalization as the existing college provisioning schema.
    email: EmailStr = Field(max_length=255)
    password: SecretStr = Field(min_length=1, max_length=MAX_PASSWORD_BYTES, repr=False)


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    invitation: SecretStr = Field(min_length=43, max_length=43, repr=False)
    password: SecretStr = Field(min_length=MIN_NEW_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES, repr=False)

    @field_validator("password")
    @classmethod
    def check_password_bytes(cls, password: SecretStr) -> SecretStr:
        if len(password.get_secret_value().encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError("Password is too long.")
        return password


class AccessTokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"


class LoginResponse(AccessTokenResponse):
    pass


class CurrentUserResponse(BaseModel):
    id: UUID
    email: str
    role: UserRole
