import secrets
import unittest
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as auth_api
from app.core.config import Settings
from app.core.passwords import hash_password
from app.main import app
from app.models.enums import AccountStatus, UserRole
from app.models.user import AuthSession, RefreshToken, User
from app.services.auth_sessions import AuthSessionService
from tests.test_login import _IsolatedSession


class AuthSessionAPITestCase(unittest.IsolatedAsyncioTestCase):
    cookie_name = "__Secure-campus_od_refresh"
    email = "student@example.com"
    origin = "https://portal.example.com"
    csrf_header = "X-CSRF-Protection"

    @classmethod
    def setUpClass(cls):
        cls.fixture_hash = hash_password("isolated synthetic fixture password")

    def setUp(self):
        self.enterContext(patch(
            "pg8000.dbapi.connect", side_effect=AssertionError("Tests must not connect to PostgreSQL"),
        ))
        config = Settings(
            _env_file=None,
            JWT_SIGNING_SECRET=secrets.token_urlsafe(48),
            JWT_ISSUER="campus-od-test",
            JWT_AUDIENCE="campus-od-test-api",
            AUTH_SESSION_LIFETIME_MINUTES=30,
            AUTH_REFRESH_TOKEN_LIFETIME_MINUTES=10,
        )
        self.enterContext(patch("app.core.access_tokens.settings", config))
        self.enterContext(patch("app.dependencies.auth_origin.settings", SimpleNamespace(CORS_ORIGINS=[self.origin])))
        self.enterContext(patch.object(auth_api, "settings", config))
        self.now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        self.clock = self.enterContext(patch("app.services.auth_sessions._utc_now", return_value=self.now))

        engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        self.factory = sessionmaker(bind=engine, class_=_IsolatedSession)
        self.get_factory = self.enterContext(patch.object(auth_api, "get_session_factory", return_value=self.factory))
        self.current_user_factory = self.enterContext(patch(
            "app.dependencies.auth.get_session_factory", return_value=self.factory,
        ))

        metadata = sa.MetaData()
        users = User.__table__.to_metadata(metadata)
        AuthSession.__table__.to_metadata(metadata)
        tokens = RefreshToken.__table__.to_metadata(metadata)
        for index in tokens.indexes:
            predicate = index.dialect_options["postgresql"].get("where")
            if predicate is not None:
                index.dialect_options["sqlite"]["where"] = predicate

        self.user_id = uuid4()
        with engine.begin() as db:
            db.exec_driver_sql("PRAGMA foreign_keys = ON")
            metadata.create_all(db)
            db.execute(users.insert().values(
                id=self.user_id, email=self.email, hashed_password=self.fixture_hash,
                role=UserRole.STUDENT, account_status=AccountStatus.ACTIVE, created_at=self.now, updated_at=self.now,
            ))

        self.service = AuthSessionService(
            session_factory=self.factory, session_lifetime=timedelta(minutes=30), refresh_lifetime=timedelta(minutes=10),
        )
        self.initial = self.service.create_session(self.user_id)

    async def asyncSetUp(self):
        self.client = await self.enterAsyncContext(
            AsyncClient(transport=ASGITransport(app=app), base_url="https://api.example.com"),
        )

    async def post(self, token, *, headers=None):
        headers = list(headers if headers is not None else [("Origin", self.origin), (self.csrf_header, "1")])
        if token is not None:
            headers.append(("Cookie", f"{self.cookie_name}={token}"))
        return await self.client.post(self.path, headers=headers)

    def refresh_cookie(self, response):
        cookies = SimpleCookie(response.headers["set-cookie"])
        self.assertEqual(set(cookies), {self.cookie_name})
        cookie = cookies[self.cookie_name]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "lax")
        self.assertEqual(cookie["path"], "/api/v1/auth")
        self.assertEqual(cookie["domain"], "")
        return cookie

    def assert_cookie_cleared(self, response):
        cookie = self.refresh_cookie(response)
        self.assertFalse(cookie.value)
        self.assertEqual(cookie["max-age"], "0")

    def assert_session_revoked(self):
        with self.factory() as db:
            self.assertIsNotNone(db.get(AuthSession, self.initial.session_id).revoked_at)
            self.assertIsNone(db.scalar(sa.select(RefreshToken.id).where(
                RefreshToken.session_id == self.initial.session_id, RefreshToken.is_revoked.is_(False),
            )))

    def assert_initial_token_unchanged(self):
        with self.factory() as db:
            token = db.scalars(sa.select(RefreshToken)).one()
            self.assertFalse(token.is_revoked)
            self.assertIsNone(token.consumed_at)
            self.assertIsNone(db.get(AuthSession, self.initial.session_id).revoked_at)
