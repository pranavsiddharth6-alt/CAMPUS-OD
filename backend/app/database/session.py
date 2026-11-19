"""Database session and engine management for PostgreSQL using SQLAlchemy 2.0.

Sri Krishna Arts and Science College (SKASC) - Campus OD
Uses pg8000 (pure-Python) driver for Windows Application Control compatibility.
"""
import ssl
import time
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from app.core.config import settings

# Declarative Base for all SQLAlchemy 2.0 models
Base = declarative_base()

# SQLAlchemy 2.0 Engine for PostgreSQL
_engine = None
_SessionLocal = None


def create_db_ssl_context() -> ssl.SSLContext:
    """Build a verified TLS context for both the application and Alembic."""
    if not settings.SUPABASE_CA_CERT_PATH:
        return ssl.create_default_context()

    ca_path = Path(settings.SUPABASE_CA_CERT_PATH).expanduser()
    if not ca_path.is_absolute():
        ca_path = Path(__file__).resolve().parents[2] / ca_path
    return ssl.create_default_context(cafile=str(ca_path))


def get_engine():
    """Lazily initialize the SQLAlchemy engine to ensure settings are loaded."""
    global _engine, _SessionLocal
    if _engine is None:
        if settings.ENVIRONMENT == "local-demo":
            from app.database.demo import DemoSession, create_demo_engine

            directory = settings.LOCAL_DEMO_DIR
            if directory is None or not (directory / "campus_od.sqlite3").is_file():
                raise ValueError("Initialize the local demo database before starting the demo.")
            _engine = create_demo_engine(directory)
            _SessionLocal = sessionmaker(bind=_engine, class_=DemoSession, autoflush=False, expire_on_commit=False)
            return _engine

        if not settings.DATABASE_URL:
            raise ValueError("DATABASE_URL is not configured in environment settings.")

        # Normalize URL scheme to postgresql+pg8000://
        # Handles both bare "postgresql://" and already-specified driver URLs
        url = settings.DATABASE_URL
        scheme, _, rest = url.partition("://")
        if "+" not in scheme:
            # Bare postgresql:// — add pg8000 driver
            url = f"postgresql+pg8000://{rest}"
        elif not scheme.endswith("+pg8000"):
            # Wrong driver specified (e.g. +psycopg) — replace with pg8000
            base_scheme = scheme.split("+")[0]
            url = f"{base_scheme}+pg8000://{rest}"

        _engine = create_engine(
            url,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,  # Automatically verify connections before use
            connect_args={
                "ssl_context": create_db_ssl_context(),
                "timeout": 10,               # pg8000-compatible connection timeout (seconds)
            },
            future=True,
        )
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_engine,
            expire_on_commit=False,
            future=True,
        )
    return _engine


def get_session_factory():
    """Return the configured session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a transactional database session."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_db_connection() -> dict:
    """Test connectivity to the configured database and return status metadata."""
    start_time = time.time()
    database = "SQLite" if settings.ENVIRONMENT == "local-demo" else "PostgreSQL"
    try:
        engine = get_engine()
        with engine.connect() as conn:
            query = "SELECT sqlite_version();" if database == "SQLite" else "SELECT version();"
            result = conn.execute(text(query)).fetchone()
            latency_ms = round((time.time() - start_time) * 1000, 2)
            version_str = result[0] if result else "Unknown"
            return {
                "connected": True,
                "database": database,
                "version": version_str,
                "latency_ms": latency_ms,
                "error": None,
            }
    except Exception as exc:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "connected": False,
            "database": database,
            "version": None,
            "latency_ms": latency_ms,
            "error": "Local demo database is unavailable." if database == "SQLite" else str(exc),
        }
