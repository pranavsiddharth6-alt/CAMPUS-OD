import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import jwt
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.access_tokens import create_access_token
from app.core.config import Settings
from app.core.passwords import hash_password
from app.dependencies.auth import AuthenticatedUser, get_current_user
from app.models.enums import AccountStatus, UserRole
from app.models.user import AuthSession, User


class CurrentUserDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_hash = hash_password("isolated synthetic fixture password")

    def setUp(self):
        self.signing_key = secrets.token_urlsafe(48)
        self.settings = Settings(
            _env_file=None,
            JWT_SIGNING_SECRET=self.signing_key,
            JWT_ISSUER="campus-od-test",
            JWT_AUDIENCE="campus-od-test-api",
            JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_MINUTES=10,
        )
        config = patch("app.core.access_tokens.settings", self.settings)
        config.start()
        self.addCleanup(config.stop)

        engine = sa.create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        self.addCleanup(engine.dispose)
        self.factory = sessionmaker(bind=engine)
        session_factory = patch("app.dependencies.auth.get_session_factory", return_value=self.factory)
        self.get_factory = session_factory.start()
        self.addCleanup(session_factory.stop)

        metadata = sa.MetaData()
        self.users = User.__table__.to_metadata(metadata)
        self.sessions = AuthSession.__table__.to_metadata(metadata)
        self.user_id, self.session_id, self.other_user_id = uuid4(), uuid4(), uuid4()
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        with engine.begin() as db:
            db.exec_driver_sql("PRAGMA foreign_keys = ON")
            metadata.create_all(db)
            db.execute(self.users.insert(), [
                {
                    "id": user_id, "email": email, "role": UserRole.STUDENT,
                    "account_status": AccountStatus.ACTIVE, "hashed_password": self.fixture_hash,
                    "created_at": self.now, "updated_at": self.now,
                }
                for user_id, email in (
                    (self.user_id, "first@example.com"), (self.other_user_id, "second@example.com"),
                )
            ])
            db.execute(self.sessions.insert().values(
                id=self.session_id, user_id=self.user_id, created_at=self.now - timedelta(minutes=1),
                expires_at=self.now + timedelta(hours=1),
            ))

    def credentials(self, user_id=None, session_id=None):
        return HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=create_access_token(user_id or self.user_id, session_id or self.session_id),
        )

    def assert_unauthorized(self, credentials):
        with self.assertRaises(HTTPException) as caught:
            get_current_user(credentials)
        error = caught.exception
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.detail, "Invalid authentication credentials.")
        self.assertEqual(error.headers, {"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
        return error

    def set_session(self, **changes):
        with self.factory.begin() as db:
            db.execute(self.sessions.update().where(self.sessions.c.id == self.session_id).values(**changes))

    def test_valid_token_resolves_current_database_role(self):
        credentials = self.credentials()
        with self.factory.begin() as db:
            db.execute(self.users.update().where(self.users.c.id == self.user_id).values(role=UserRole.TUTOR))

        identity = get_current_user(credentials)
        self.assertEqual(identity, AuthenticatedUser(self.user_id, self.session_id, UserRole.TUTOR, "first@example.com"))
        self.assertFalse(hasattr(identity, "hashed_password"))
        self.assertFalse(hasattr(identity, "credentials"))

    def test_missing_credentials_fail_before_database_access(self):
        self.assert_unauthorized(None)
        self.get_factory.assert_not_called()

    def test_invalid_or_expired_token_fails_before_database_access(self):
        now = int(self.now.replace(tzinfo=timezone.utc).timestamp())
        expired = jwt.encode(
            {
                "sub": str(self.user_id), "sid": str(self.session_id), "jti": str(uuid4()),
                "iss": self.settings.JWT_ISSUER, "aud": self.settings.JWT_AUDIENCE,
                "iat": now - 10, "nbf": now - 10, "exp": now - 1,
            },
            self.signing_key, algorithm="HS256", headers={"typ": "at+jwt"},
        )
        for token in ("malformed", expired):
            self.assert_unauthorized(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
        self.get_factory.assert_not_called()

    def test_inactive_or_missing_user_is_rejected(self):
        with self.factory.begin() as db:
            db.execute(self.users.update().where(self.users.c.id == self.user_id).values(
                account_status=AccountStatus.DISABLED,
            ))
        self.assert_unauthorized(self.credentials())
        self.assert_unauthorized(self.credentials(user_id=uuid4()))

    def test_missing_session_is_rejected(self):
        self.assert_unauthorized(self.credentials(session_id=uuid4()))

    def test_pending_user_is_rejected_even_with_existing_session(self):
        with self.factory.begin() as db:
            db.execute(self.users.update().where(self.users.c.id == self.user_id).values(
                account_status=AccountStatus.PENDING_ACTIVATION, hashed_password=None,
            ))
        self.assert_unauthorized(self.credentials())

    def test_revoked_session_is_rejected(self):
        self.set_session(revoked_at=self.now)
        self.assert_unauthorized(self.credentials())

    def test_expired_session_is_rejected(self):
        self.set_session(expires_at=self.now)
        self.assert_unauthorized(self.credentials())

    def test_session_with_future_creation_is_rejected(self):
        self.set_session(created_at=self.now + timedelta(minutes=1))
        self.assert_unauthorized(self.credentials())

    def test_session_bound_to_a_different_active_user_is_rejected(self):
        self.assert_unauthorized(self.credentials(user_id=self.other_user_id))

    def test_invalid_jwt_configuration_is_sanitized(self):
        credentials = self.credentials()
        config = self.settings.model_copy(update={"JWT_SIGNING_SECRET": None})
        with patch("app.core.access_tokens.settings", config):
            self.assert_unauthorized(credentials)
        self.get_factory.assert_not_called()

    def test_database_failure_is_sanitized(self):
        db = MagicMock()
        db.__enter__.return_value.execute.side_effect = SQLAlchemyError("synthetic driver details")
        self.get_factory.return_value = lambda: db
        error = self.assert_unauthorized(self.credentials())
        self.assertTrue(error.__suppress_context__)
        db.__exit__.assert_called_once()
