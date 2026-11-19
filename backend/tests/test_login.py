import asyncio
import secrets
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from http.cookies import SimpleCookie
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import auth as login_api
from app.core.access_tokens import JWTConfigurationError, verify_access_token
from app.core.config import Settings
from app.core.passwords import hash_password, verify_password
from app.main import app
from app.models.enums import AccountStatus, UserRole
from app.models.user import AuthSession, RefreshToken, User
from app.schemas.user import UserCreate


class _IsolatedSession(Session):
    def connection(self, bind_arguments=None, execution_options=None):
        # SQLite fixtures exercise commit and rollback, not PostgreSQL isolation or row locking.
        if execution_options == {"isolation_level": "READ COMMITTED"}:
            execution_options = None
        return super().connection(bind_arguments=bind_arguments, execution_options=execution_options)


class LoginTests(unittest.IsolatedAsyncioTestCase):
    path = "/api/v1/auth/login"
    origin = "https://portal.example.com"
    email = "Student@example.com"
    password = "synthetic test password"

    @classmethod
    def setUpClass(cls):
        cls.saved_hash = hash_password(cls.password)

    def setUp(self):
        postgres = patch("pg8000.dbapi.connect", side_effect=AssertionError("Tests must not connect to PostgreSQL"))
        postgres.start()
        self.addCleanup(postgres.stop)

        config = Settings(
            _env_file=None, JWT_SIGNING_SECRET=secrets.token_urlsafe(48),
            JWT_ISSUER="campus-od-test", JWT_AUDIENCE="campus-od-test-api",
        )
        patches = (
            patch("app.core.access_tokens.settings", config),
            patch("app.dependencies.auth_origin.settings", SimpleNamespace(CORS_ORIGINS=[self.origin])),
            patch.object(login_api, "_rate_limit", login_api._LoginRateLimit()),
            patch.object(login_api, "_login_slots", BoundedSemaphore(2)),
        )
        for replacement in patches:
            replacement.start()
            self.addCleanup(replacement.stop)

        engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        self.factory = sessionmaker(bind=engine, class_=_IsolatedSession)
        factory = patch.object(login_api, "get_session_factory", return_value=self.factory)
        self.get_factory = factory.start()
        self.addCleanup(factory.stop)

        metadata = sa.MetaData()
        self.users = User.__table__.to_metadata(metadata)
        AuthSession.__table__.to_metadata(metadata)
        tokens = RefreshToken.__table__.to_metadata(metadata)
        for index in tokens.indexes:
            predicate = index.dialect_options["postgresql"].get("where")
            if predicate is not None:
                index.dialect_options["sqlite"]["where"] = predicate

        self.user_id = uuid4()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with engine.begin() as db:
            db.exec_driver_sql("PRAGMA foreign_keys = ON")
            metadata.create_all(db)
            db.execute(self.users.insert().values(
                id=self.user_id, email=self.email, hashed_password=self.saved_hash,
                role=UserRole.STUDENT, account_status=AccountStatus.ACTIVE, created_at=now, updated_at=now,
            ))

    async def asyncSetUp(self):
        self.client = self.make_client()
        await self.client.__aenter__()
        self.addAsyncCleanup(self.client.aclose)

    def make_client(self, ip="192.0.2.10"):
        return AsyncClient(
            transport=ASGITransport(app=app, client=(ip, 50000)),
            base_url="https://api.example.com",
        )

    async def post(self, email=None, password=None):
        return await self.client.post(
            self.path, headers={"Origin": self.origin},
            json={"email": email if email is not None else self.email,
                  "password": password if password is not None else self.password},
        )

    def assert_rejected(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid email or password."})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", response.headers)

    def assert_no_sessions(self):
        with self.factory() as db:
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(AuthSession)), 0)
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(RefreshToken)), 0)

    async def test_success_commits_session_and_keeps_refresh_token_in_secure_cookie(self):
        with self.assertLogs(level="DEBUG") as logs:
            response = await self.post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(set(body), {"access_token", "token_type"})
        self.assertEqual(body["token_type"], "bearer")

        cookies = SimpleCookie(response.headers["set-cookie"])
        self.assertEqual(set(cookies), {"__Secure-campus_od_refresh"})
        cookie = cookies["__Secure-campus_od_refresh"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "lax")
        self.assertEqual(cookie["path"], "/api/v1/auth")
        self.assertEqual(cookie["domain"], "")
        self.assertTrue(cookie["expires"])
        self.assertFalse(cookie.value in response.text)
        output = "\n".join(logs.output)
        self.assertFalse(any(value in output for value in (
            cookie.value, self.saved_hash, self.password, body["access_token"],
        )))

        claims = verify_access_token(body["access_token"])
        self.assertEqual(claims.sub, self.user_id)
        with self.factory() as fresh_db:
            session = fresh_db.get(AuthSession, claims.sid)
            token = fresh_db.scalars(sa.select(RefreshToken)).one()
            self.assertEqual(session.user_id, self.user_id)
            self.assertEqual(token.session_id, claims.sid)
            self.assertTrue(token.token_hash == sha256(cookie.value.encode("ascii")).hexdigest())
            self.assertFalse(token.token_hash == cookie.value)

    async def test_wrong_password_has_generic_response(self):
        self.assert_rejected(await self.post(password="incorrect"))
        self.assert_no_sessions()

    async def test_unknown_email_runs_password_verification_and_has_generic_response(self):
        with patch.object(login_api, "verify_password", wraps=verify_password) as verifier:
            self.assert_rejected(await self.post(email="missing@example.com"))
        verifier.assert_called_once()
        self.assert_no_sessions()

    async def test_inactive_user_has_generic_response_even_with_correct_password(self):
        with self.factory.begin() as db:
            db.execute(self.users.update().where(self.users.c.id == self.user_id).values(
                account_status=AccountStatus.DISABLED,
            ))
        self.assert_rejected(await self.post())
        self.assert_no_sessions()

    async def test_email_matches_provisioning_normalization_and_preserves_local_part_case(self):
        supplied = "  Student@EXAMPLE.COM  "
        provisioned = UserCreate(email=supplied, role=UserRole.STUDENT, password=self.password)
        self.assertEqual(provisioned.email, self.email)
        self.assertEqual((await self.post(email=supplied)).status_code, 200)
        self.assert_rejected(await self.post(email=self.email.lower()))

    async def test_pending_account_without_a_hash_uses_dummy_verification(self):
        with self.factory.begin() as db:
            db.execute(self.users.update().where(self.users.c.id == self.user_id).values(
                account_status=AccountStatus.PENDING_ACTIVATION, hashed_password=None,
            ))
        with patch.object(login_api, "verify_password", wraps=verify_password) as verifier:
            self.assert_rejected(await self.post())
        verifier.assert_called_once()
        self.assertTrue(verifier.call_args.args[1] == login_api._dummy_password_hash())
        self.assert_no_sessions()

    async def test_auth_version_change_during_password_verification_rejects_login(self):
        def verify_then_advance(password, stored_hash):
            verified = verify_password(password, stored_hash)
            with self.factory.begin() as db:
                db.execute(self.users.update().where(self.users.c.id == self.user_id).values(auth_version=1))
            return verified

        with patch.object(login_api, "verify_password", side_effect=verify_then_advance):
            self.assert_rejected(await self.post())
        self.assert_no_sessions()

    async def test_account_throttle_is_shared_across_ips_and_canonical_email_forms(self):
        with patch.object(login_api, "_PER_ACCOUNT_LIMIT", 1):
            self.assert_rejected(await self.post(password="incorrect"))
            async with self.make_client("192.0.2.11") as another:
                limited = await another.post(
                    self.path, headers={"Origin": self.origin},
                    json={"email": "  Student@EXAMPLE.COM  ", "password": self.password},
                )
        self.assertEqual(limited.status_code, 429)
        self.assertGreater(int(limited.headers["retry-after"]), 0)
        self.assertNotIn("set-cookie", limited.headers)
        self.assertEqual(self.get_factory.call_count, 1)
        self.assert_no_sessions()

    async def test_rate_limits_use_the_server_peer_and_bound_worker_total(self):
        with patch.object(login_api, "_PER_IP_LIMIT", 1), patch.object(login_api, "_PER_WORKER_LIMIT", 2):
            self.assert_rejected(await self.post(email="unknown-one@example.com"))
            same_peer = await self.client.post(
                self.path, headers={"Origin": self.origin, "X-Forwarded-For": "192.0.2.254"},
                json={"email": "unknown-two@example.com", "password": self.password},
            )
            self.assertEqual(same_peer.status_code, 429)
            async with self.make_client("192.0.2.11") as second:
                allowed = await second.post(
                    self.path, headers={"Origin": self.origin},
                    json={"email": "unknown-three@example.com", "password": self.password},
                )
                self.assert_rejected(allowed)
            async with self.make_client("192.0.2.12") as third:
                limited = await third.post(
                    self.path, headers={"Origin": self.origin},
                    json={"email": "unknown-four@example.com", "password": self.password},
                )
                self.assertEqual(limited.status_code, 429)
        self.assertEqual(self.get_factory.call_count, 2)

    async def test_concurrency_saturation_rejects_without_queuing_password_work(self):
        entered, release = Event(), Event()

        def busy_worker(credentials):
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("Login worker did not receive release")
            raise login_api._unauthorized()

        with patch.object(login_api, "_login_slots", BoundedSemaphore(1)):
            with patch.object(login_api, "_authenticate_login", side_effect=busy_worker) as worker:
                admitted = asyncio.create_task(self.post())
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                    result = await asyncio.wait_for(self.post(), timeout=3)
                    self.assertEqual(result.status_code, 429)
                    self.assertEqual(result.headers["retry-after"], "1")
                    worker.assert_called_once()
                finally:
                    release.set()
                    self.assert_rejected(await admitted)
            self.assert_rejected(await self.post(password="incorrect"))

    async def test_origin_and_content_type_are_checked_before_password_processing(self):
        credentials = {"email": self.email, "password": self.password}
        for headers in ({}, {"Origin": "null"}, {"Origin": "https://untrusted.example.com"}):
            denied = await self.client.post(self.path, headers=headers, json=credentials)
            self.assertEqual(denied.status_code, 403)
            self.assertNotIn("set-cookie", denied.headers)
        denied = await self.client.post(
            self.path, headers={"Origin": self.origin, "Content-Type": "text/plain"},
            content="not JSON",
        )
        self.assertEqual(denied.status_code, 415)
        self.get_factory.assert_not_called()

    async def test_invalid_body_does_not_echo_credentials(self):
        response = await self.client.post(
            self.path, headers={"Origin": self.origin},
            json={"email": self.email, "password": {"invalid": self.password}},
        )
        self.assert_rejected(response)
        self.assertFalse(self.password in response.text)
        self.get_factory.assert_not_called()

    async def test_session_commit_failure_rolls_back_and_returns_no_credentials(self):
        def fail_commit(db):
            raise SQLAlchemyError("synthetic internal database failure")

        sa.event.listen(self.factory, "before_commit", fail_commit)
        try:
            failed = await self.post()
        finally:
            sa.event.remove(self.factory, "before_commit", fail_commit)

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json(), {"detail": "Authentication is unavailable."})
        self.assertNotIn("set-cookie", failed.headers)
        self.assert_no_sessions()

    async def test_failed_jwt_configuration_does_not_create_a_session(self):
        with patch.object(login_api, "create_access_token", side_effect=JWTConfigurationError("synthetic detail")):
            failed = await self.post()
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("set-cookie", failed.headers)
        self.assert_no_sessions()

    async def test_password_change_before_session_insert_rejects_old_verification(self):
        new_hash = hash_password("another synthetic password")

        def verify_then_change(password, saved_hash):
            verified = verify_password(password, saved_hash)
            with self.factory.begin() as db:
                db.execute(self.users.update().where(self.users.c.id == self.user_id).values(hashed_password=new_hash))
            return verified

        with patch.object(login_api, "verify_password", side_effect=verify_then_change):
            self.assert_rejected(await self.post())
        self.assert_no_sessions()
