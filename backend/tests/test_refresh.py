import asyncio
import secrets
from datetime import timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from threading import Event
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import auth as auth_api
from app.core.access_tokens import JWTConfigurationError, verify_access_token
from app.models.enums import AccountStatus
from app.models.user import AuthSession, RefreshToken, User
from tests.auth_api_fixture import AuthSessionAPITestCase


class RefreshTests(AuthSessionAPITestCase):
    path = "/api/v1/auth/refresh"

    def assert_rejected(self, response, *, clear_cookie=True):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid authentication credentials."})
        self.assertEqual(response.headers["cache-control"], "no-store")
        if clear_cookie:
            self.assert_cookie_cleared(response)
        else:
            self.assertNotIn("set-cookie", response.headers)

    async def test_success_consumes_token_and_returns_access_jwt_with_replacement_cookie(self):
        with self.assertLogs(level="DEBUG") as logs:
            response = await self.post(self.initial.refresh_token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        body = response.json()
        self.assertEqual(set(body), {"access_token", "token_type"})
        self.assertEqual(body["token_type"], "bearer")
        claims = verify_access_token(body["access_token"])
        self.assertEqual((claims.sub, claims.sid), (self.user_id, self.initial.session_id))

        replacement = self.refresh_cookie(response)
        self.assertFalse(replacement.value == self.initial.refresh_token)
        self.assertFalse(replacement.value in response.text)
        self.assertFalse(any(value in "\n".join(logs.output) for value in (
            self.initial.refresh_token, replacement.value, body["access_token"],
        )))
        with self.factory() as db:
            previous = db.scalars(sa.select(RefreshToken).where(RefreshToken.is_revoked.is_(True))).one()
            active = db.scalars(sa.select(RefreshToken).where(RefreshToken.is_revoked.is_(False))).one()
            self.assertEqual(previous.consumed_at, self.now)
            self.assertEqual(active.session_id, self.initial.session_id)
            self.assertTrue(active.token_hash == sha256(replacement.value.encode("ascii")).hexdigest())
            self.assertEqual(active.expires_at, self.now + timedelta(minutes=10))
            self.assertEqual(parsedate_to_datetime(replacement["expires"]).replace(tzinfo=None), active.expires_at)

    async def test_replacement_and_cookie_expiry_are_capped_by_absolute_session_expiry(self):
        token = self.initial.refresh_token
        for minutes in (9, 18, 26):
            self.clock.return_value = self.now + timedelta(minutes=minutes)
            response = await self.post(token)
            self.assertEqual(response.status_code, 200)
            replacement = self.refresh_cookie(response)
            token = replacement.value

        with self.factory() as db:
            active = db.scalars(sa.select(RefreshToken).where(RefreshToken.is_revoked.is_(False))).one()
            session = db.get(AuthSession, self.initial.session_id)
            self.assertEqual(session.expires_at, self.initial.session_expires_at)
            self.assertEqual(active.expires_at, session.expires_at)
            self.assertEqual(parsedate_to_datetime(replacement["expires"]).replace(tzinfo=None), session.expires_at)

    async def test_expired_refresh_token_is_rejected_and_cleared(self):
        self.clock.return_value = self.initial.refresh_expires_at
        self.assert_rejected(await self.post(self.initial.refresh_token))
        self.assert_initial_token_unchanged()

    async def test_absolute_session_expiry_is_rejected_and_cleared(self):
        # Shorten the session while leaving its persisted token valid past the new deadline.
        deadline = self.now + timedelta(minutes=5)
        with self.factory.begin() as db:
            db.get(AuthSession, self.initial.session_id).expires_at = deadline
        self.clock.return_value = deadline
        self.assert_rejected(await self.post(self.initial.refresh_token))
        self.assert_initial_token_unchanged()

    async def test_revoked_session_is_rejected_and_cleared(self):
        self.service.revoke_session(self.initial.session_id, user_id=self.user_id)
        self.assert_rejected(await self.post(self.initial.refresh_token))
        self.assert_session_revoked()

    async def test_pending_or_disabled_account_cannot_rotate_existing_token(self):
        for account_status in (AccountStatus.DISABLED, AccountStatus.PENDING_ACTIVATION):
            with self.factory.begin() as db:
                db.execute(sa.update(User).where(User.id == self.user_id).values(
                    account_status=account_status, hashed_password=None,
                ))
            self.assert_rejected(await self.post(self.initial.refresh_token))
            self.assert_initial_token_unchanged()

    async def test_replay_commits_revocation_of_only_the_affected_session(self):
        other = self.service.create_session(self.user_id)
        success = await self.post(self.initial.refresh_token)
        self.assertEqual(success.status_code, 200)
        replacement = self.refresh_cookie(success).value

        self.assert_rejected(await self.post(self.initial.refresh_token))
        self.assert_session_revoked()
        self.assert_rejected(await self.post(replacement))
        self.assertEqual((await self.post(other.refresh_token)).status_code, 200)

    async def test_missing_cookie_is_rejected_before_opening_database(self):
        self.assert_rejected(await self.post(None), clear_cookie=False)
        self.get_factory.assert_not_called()

    async def test_unknown_and_malformed_cookies_have_the_same_error(self):
        for token in (secrets.token_urlsafe(32), "malformed", ""):
            self.assert_rejected(await self.post(token))
        self.assert_initial_token_unchanged()

    async def test_missing_untrusted_and_duplicate_origins_do_not_change_cookies(self):
        for origins in ([], ["null"], ["https://other.example.com"], [self.origin, self.origin]):
            response = await self.post(self.initial.refresh_token, headers=[
                (self.csrf_header, "1"), *(("Origin", origin) for origin in origins),
            ])
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("set-cookie", response.headers)
        self.get_factory.assert_not_called()
        self.assert_initial_token_unchanged()

    async def test_missing_wrong_and_duplicate_csrf_headers_do_not_change_cookies(self):
        for values in ([], ["0"], ["1", "1"], ["1, 1"]):
            response = await self.post(self.initial.refresh_token, headers=[
                ("Origin", self.origin), *((self.csrf_header, value) for value in values),
            ])
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("set-cookie", response.headers)
        self.get_factory.assert_not_called()
        self.assert_initial_token_unchanged()

    async def test_failed_rotation_commit_rolls_back_and_does_not_sign(self):
        def fail_commit(db):
            raise SQLAlchemyError("synthetic failure during commit")

        sa.event.listen(self.factory, "before_commit", fail_commit)
        try:
            with patch.object(auth_api, "create_access_token") as signer:
                failed = await self.post(self.initial.refresh_token)
            signer.assert_not_called()
        finally:
            sa.event.remove(self.factory, "before_commit", fail_commit)

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json(), {"detail": "Authentication is unavailable."})
        self.assertNotIn("set-cookie", failed.headers)
        self.assert_initial_token_unchanged()
        self.assertEqual((await self.post(self.initial.refresh_token)).status_code, 200)

    async def test_signing_failure_after_rotation_clears_consumed_cookie(self):
        with patch.object(auth_api, "create_access_token", side_effect=JWTConfigurationError("synthetic detail")):
            failed = await self.post(self.initial.refresh_token)

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json(), {"detail": "Authentication is unavailable."})
        self.assert_cookie_cleared(failed)
        with self.factory() as db:
            consumed = db.scalars(sa.select(RefreshToken).where(RefreshToken.consumed_at.is_not(None))).one()
            self.assertEqual(consumed.session_id, self.initial.session_id)

    async def test_overlapping_requests_with_the_same_cookie_trigger_replay_revocation(self):
        signing, release = Event(), Event()
        create_access_token = auth_api.create_access_token

        def pause_response(user_id, session_id):
            signing.set()
            if not release.wait(timeout=5):
                raise AssertionError("First refresh request did not receive release")
            return create_access_token(user_id, session_id)

        # Overlap the requests after the first transaction commits so SQLite never shares a transaction.
        with patch.object(auth_api, "create_access_token", side_effect=pause_response) as signer:
            first = asyncio.create_task(self.post(self.initial.refresh_token))
            try:
                self.assertTrue(await asyncio.to_thread(signing.wait, 3))
                replay = await asyncio.wait_for(self.post(self.initial.refresh_token), timeout=3)
                self.assert_rejected(replay)
                self.assert_session_revoked()
            finally:
                release.set()
                first_response = await first
            signer.assert_called_once()

        self.assertEqual(first_response.status_code, 200)
        self.assert_rejected(await self.post(self.refresh_cookie(first_response).value))
