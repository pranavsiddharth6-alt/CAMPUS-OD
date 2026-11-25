from pydantic_settings import BaseSettings
from typing import Annotated, List, Union
from pydantic import Field, FiniteFloat, PositiveInt, SecretStr, field_validator
import os
from pathlib import Path


class Settings(BaseSettings):
    PROJECT_NAME: str = "Campus OD"
    TAGLINE: str = "Smart On-Duty Management System"
    INSTITUTION: str = "Sri Krishna Arts and Science College (SKASC)"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Host & Port
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # CORS Configuration
    CORS_ORIGINS: Union[str, List[str]] = "http://localhost:5173,http://127.0.0.1:5173"

    # PostgreSQL Database Configuration
    DATABASE_URL: str = "postgresql+pg8000://postgres:postgres@localhost:5432/campus_od"
    SUPABASE_CA_CERT_PATH: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30

    # Validate JWT configuration at use so health checks can run independently.
    JWT_SIGNING_SECRET: SecretStr | None = None
    JWT_ISSUER: str | None = None
    JWT_AUDIENCE: str | None = None
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_MINUTES: int | str = 10
    AUTH_SESSION_LIFETIME_MINUTES: PositiveInt = 480
    AUTH_REFRESH_TOKEN_LIFETIME_MINUTES: PositiveInt = 120
    AUTH_INVITATION_LIFETIME_HOURS: PositiveInt = 24
    LOCAL_DEMO_DIR: Path | None = None

    # Storage
    STORAGE_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "storage")
    MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024  # 5MB
    MAP_OD_RADIUS_METRES: Annotated[FiniteFloat, Field(gt=0)] = 250
    MAP_OD_MAX_ACCURACY_METRES: Annotated[FiniteFloat, Field(gt=0)] = 100

    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    class Config:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
