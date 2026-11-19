import secrets
from datetime import timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app.core.access_tokens import create_access_token
from app.models.enums import AccountStatus, UserRole
from app.models.user import AuthSession, User
from tests.auth_api_fixture import AuthSessionAPITestCase


class LogoutAndMeTests(AuthSessionAPITestCase):
    path = "/api/v1/auth/logout"
    me_path = "/api/v1/auth/me"

    async def get_me(self, token):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return await self.client.get(self.me_path, headers=headers)

    def access_token(self):
        return create_access_token(self.user_id, self.initial.session_id)

    def assert_logout(self, response):
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assert_cookie_cleared(response)

    def assert_unauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid authentication credentials."})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", response.headers)

    async def test_logout_commits_revocation_and_invalidates_the_access_jwt(self):
        access_token = self.access_token()
        self.assertEqual((await self.get_me(access_token)).status_code, 200)
        self.client.cookies.set(self.cookie_name, self.initial.refresh_token, domain="api.example.com",
                                path="/api/v1/auth")
        self.assert_logout(await self.post(None))
        self.assert_session_revoked()
        self.assertFalse(any(cookie.name == self.cookie_name for cookie in self.client.cookies.jar))
        self.assert_unauthorized(await self.get_me(access_token))

    async def test_missing_cookie_is_idempotent_without_storage_access(self):
        self.assert_logout(await self.post(None))
        self.get_factory.assert_not_called()
        self.assert_initial_token_unchanged()

    async def test_malformed_and_unknown_cookies_are_idempotent(self):
        for token in ("", "malformed", secrets.token_urlsafe(32)):
            self.assert_logout(await self.post(token))
        self.assert_initial_token_unchanged()

    async def test_expired_unconsumed_token_clears_cookie_without_revocation(self):
        self.clock.return_value = self.initial.refresh_expires_at
        self.assert_logout(await self.post(self.initial.refresh_token))
        self.assert_initial_token_unchanged()

    async def test_repeated_logout_keeps_original_revocation_timestamp(self):
        self.assert_logout(await self.post(self.initial.refresh_token))
        self.clock.return_value = self.now + timedelta(minutes=1)
        self.assert_logout(await self.post(self.initial.refresh_token))
        self.assert_session_revoked()
        with self.factory() as db:
            self.assertEqual(db.get(AuthSession, self.initial.session_id).revoked_at, self.now)

    async def test_consumed_cookie_revokes_only_its_own_session(self):
        self.clock.return_value = self.now + timedelta(minutes=9)
        replacement = self.service.rotate_refresh_token(self.initial.refresh_token)
        other_user_id = uuid4()
        with self.factory.begin() as db:
            db.add(User(id=other_user_id, email="other@example.com", hashed_password=self.fixture_hash,
                        role=UserRole.TUTOR, account_status=AccountStatus.ACTIVE,
                        created_at=self.now, updated_at=self.now))
        other_session = self.service.create_session(other_user_id)
        same_user_session = self.service.create_session(self.user_id)
        self.clock.return_value = self.now + timedelta(minutes=11)

        response = await self.client.post(
            self.path,
            headers={
                "Origin": self.origin,
                self.csrf_header: "1",
                "Cookie": f"{self.cookie_name}={self.initial.refresh_token}",
                "Authorization": f"Bearer {create_access_token(other_user_id, other_session.session_id)}",
            },
            json={"user_id": str(other_user_id), "session_id": str(other_session.session_id)},
        )
        self.assert_logout(response)
        self.assert_session_revoked()
        self.assertTrue(self.service.is_session_active(other_session.session_id, user_id=other_user_id))
        self.assertTrue(self.service.is_session_active(same_user_session.session_id, user_id=self.user_id))
        self.assert_logout(await self.post(replacement.refresh_token))

    async def test_origin_is_required_before_cookie_or_session_changes(self):
        for origins in ([], ["null"], ["https://untrusted.example.com"], [self.origin, self.origin]):
            response = await self.post(self.initial.refresh_token, headers=[
                (self.csrf_header, "1"), *(("Origin", origin) for origin in origins),
            ])
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("set-cookie", response.headers)
        self.get_factory.assert_not_called()
        self.assert_initial_token_unchanged()

    async def test_csrf_header_is_required_before_cookie_or_session_changes(self):
        for values in ([], ["0"], ["1", "1"], ["1, 1"]):
            response = await self.post(self.initial.refresh_token, headers=[
                ("Origin", self.origin), *((self.csrf_header, value) for value in values),
            ])
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("set-cookie", response.headers)
        self.get_factory.assert_not_called()
        self.assert_initial_token_unchanged()

    async def test_logout_commit_failure_rolls_back_and_leaves_cookie_for_retry(self):
        def fail_commit(db):
            db.flush()
            raise SQLAlchemyError("synthetic driver details")

        sa.event.listen(self.factory, "before_commit", fail_commit)
        try:
            failed = await self.post(self.initial.refresh_token)
        finally:
            sa.event.remove(self.factory, "before_commit", fail_commit)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json(), {"detail": "Authentication is unavailable."})
        self.assertEqual(failed.headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", failed.headers)
        self.assert_initial_token_unchanged()
        self.assert_logout(await self.post(self.initial.refresh_token))
        self.assert_session_revoked()

    async def test_me_returns_only_current_safe_user_fields(self):
        token = self.access_token()
        with self.factory.begin() as db:
            user = db.get(User, self.user_id)
            user.email = "updated@example.com"
            user.role = UserRole.TUTOR

        response = await self.get_me(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "id": str(self.user_id), "email": "updated@example.com", "role": UserRole.TUTOR.value,
        })
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("set-cookie", response.headers)

    async def test_me_requires_bearer_and_rejects_invalid_or_expired_jwt(self):
        with patch("app.core.access_tokens.datetime") as clock:
            clock.now.return_value = self.now.replace(tzinfo=timezone.utc) - timedelta(hours=2)
            expired = self.access_token()
        response = await self.client.get(self.me_path, headers={
            "Cookie": f"{self.cookie_name}={self.initial.refresh_token}",
        })
        self.assert_unauthorized(response)
        for token in ("malformed", expired):
            self.assert_unauthorized(await self.get_me(token))
        self.current_user_factory.assert_not_called()

    async def test_me_rejects_user_deactivated_after_jwt_issuance(self):
        token = self.access_token()
        with self.factory.begin() as db:
            db.get(User, self.user_id).account_status = AccountStatus.DISABLED
        self.assert_unauthorized(await self.get_me(token))

    async def test_me_rejects_expired_session(self):
        token = self.access_token()
        with self.factory.begin() as db:
            db.get(AuthSession, self.initial.session_id).expires_at = self.now
        self.assert_unauthorized(await self.get_me(token))

    async def test_me_rejects_jwt_bound_to_another_user(self):
        other_user_id = uuid4()
        with self.factory.begin() as db:
            db.add(User(id=other_user_id, email="other@example.com", hashed_password=self.fixture_hash,
                        role=UserRole.ADMIN, account_status=AccountStatus.ACTIVE,
                        created_at=self.now, updated_at=self.now))
        token = create_access_token(other_user_id, self.initial.session_id)
        self.assert_unauthorized(await self.get_me(token))
