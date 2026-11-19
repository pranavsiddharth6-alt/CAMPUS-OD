import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from hashlib import sha256
from threading import Event
from unittest.mock import MagicMock, Mock, call, patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import AuthSession, RefreshToken
from app.services.auth_sessions import AuthSessionService, InvalidSessionError, SessionStoreError


class AuthSessionServiceTests(unittest.TestCase):
    now = datetime(2026, 1, 1, 12)
    raw_token = "A" * 43

    def setUp(self):
        self.user_id = uuid4()
        self.session_id = uuid4()
        self.factory = Mock(spec=sessionmaker)
        self.db, self.transaction = self.mock_transaction()
        self.factory.begin.return_value = self.transaction
        self.service = AuthSessionService(
            session_factory=self.factory, session_lifetime=timedelta(days=2),
            refresh_lifetime=timedelta(days=3),
        )
        clock = patch("app.services.auth_sessions._utc_now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    @staticmethod
    def mock_transaction():
        db = Mock(spec=Session)
        transaction = MagicMock()
        transaction.__enter__.return_value = db
        return db, transaction

    @staticmethod
    def pg_sql(statement):
        return str(statement.compile(dialect=postgresql.dialect()))

    def session_row(self, **changes):
        values = dict(
            id=self.session_id, user_id=self.user_id, created_at=self.now - timedelta(hours=1),
            expires_at=self.now + timedelta(hours=1), revoked_at=None,
        )
        return AuthSession(**(values | changes))

    def token_row(self, **changes):
        values = dict(
            id=uuid4(), session_id=self.session_id, user_id=self.user_id,
            token_hash=sha256(self.raw_token.encode()).hexdigest(),
            created_at=self.now - timedelta(hours=1), expires_at=self.now + timedelta(minutes=10),
            consumed_at=None, is_revoked=False,
        )
        return RefreshToken(**(values | changes))

    def configure_rotation(self, session, token):
        self.db.execute.return_value.one_or_none.return_value = (self.session_id, self.user_id)
        self.db.scalar.side_effect = [True, session, token]

    def test_create_session_returns_opaque_token_but_stores_only_digest(self):
        self.db.scalar.return_value = True

        def assign_id():
            self.db.add.call_args.args[0].id = self.session_id

        self.db.flush.side_effect = assign_id
        credentials = self.service.create_session(self.user_id)
        session, token = [record.args[0] for record in self.db.add.call_args_list]
        self.assertIsInstance(session, AuthSession)
        self.assertIsInstance(token, RefreshToken)
        self.assertEqual((session.id, token.session_id, token.user_id), (self.session_id, self.session_id, self.user_id))
        self.assertRegex(credentials.refresh_token, r"^[A-Za-z0-9_-]{43}$")
        self.assertTrue(token.token_hash == sha256(credentials.refresh_token.encode()).hexdigest())
        self.assertFalse(token.token_hash == credentials.refresh_token)
        self.assertNotIn("refresh_token", repr(credentials))
        self.assertEqual(token.expires_at, session.expires_at)
        self.assertEqual(credentials.refresh_expires_at, session.expires_at)
        self.assertIn("FOR SHARE", self.pg_sql(self.db.scalar.call_args.args[0]))
        self.transaction.__exit__.assert_called_once_with(None, None, None)

    def test_creation_rejects_inactive_or_missing_users(self):
        for state in (False, None):
            with self.subTest(state=state):
                self.db.scalar.return_value = state
                with self.assertRaises(InvalidSessionError):
                    self.service.create_session(self.user_id)
        self.db.add.assert_not_called()

    def test_rotation_locks_then_rereads_and_flushes_before_inserting(self):
        session, previous = self.session_row(), self.token_row()
        self.configure_rotation(session, previous)

        def check_consumption_before_insert():
            self.assertTrue(previous.is_revoked)
            self.assertEqual(previous.consumed_at, self.now)
            self.db.add.assert_not_called()

        self.db.flush.side_effect = check_consumption_before_insert
        credentials = self.service.rotate_refresh_token(self.raw_token, expected_user_id=self.user_id)
        replacement = self.db.add.call_args.args[0]
        self.assertEqual(credentials.session_id, session.id)
        self.assertTrue(replacement.token_hash == sha256(credentials.refresh_token.encode()).hexdigest())
        self.assertFalse(replacement.token_hash == previous.token_hash)
        self.assertEqual(replacement.expires_at, session.expires_at)
        statements = [self.pg_sql(call.args[0]) for call in self.db.scalar.call_args_list]
        self.assertIn("FOR SHARE", statements[0])
        self.assertIn("FOR UPDATE", statements[1])
        self.assertIn("auth_sessions.user_id =", statements[1])
        self.assertIn("refresh_tokens.token_hash =", statements[2])
        self.assertIn("refresh_tokens.session_id =", statements[2])
        self.assertIn("refresh_tokens.user_id =", statements[2])
        self.assertEqual(
            self.db.method_calls[0], call.connection(execution_options={"isolation_level": "READ COMMITTED"})
        )
        self.transaction.__exit__.assert_called_once_with(None, None, None)

    def test_consumed_token_replay_commits_revocation_before_rejection(self):
        session = self.session_row()
        previous = self.token_row(
            is_revoked=True, consumed_at=self.now - timedelta(minutes=20),
            expires_at=self.now - timedelta(minutes=10),
        )
        self.configure_rotation(session, previous)
        with self.assertRaisesRegex(InvalidSessionError, r"^Invalid authentication session\.$"):
            self.service.rotate_refresh_token(self.raw_token)

        self.assertEqual(session.revoked_at, self.now)
        revoke = self.pg_sql(self.db.execute.call_args.args[0])
        self.assertIn("UPDATE refresh_tokens SET is_revoked", revoke)
        self.assertIn("refresh_tokens.session_id =", revoke)
        self.assertIn("refresh_tokens.user_id =", revoke)
        self.assertIn("refresh_tokens.is_revoked IS false", revoke)
        self.db.add.assert_not_called()
        self.transaction.__exit__.assert_called_once_with(None, None, None)

    def test_expired_session_or_unconsumed_token_is_rejected(self):
        states = (
            (self.session_row(expires_at=self.now), self.token_row()),
            (self.session_row(), self.token_row(expires_at=self.now)),
        )
        for session, token in states:
            with self.subTest(session_expires_at=session.expires_at, token_expires_at=token.expires_at):
                self.configure_rotation(session, token)
                with self.assertRaises(InvalidSessionError):
                    self.service.rotate_refresh_token(self.raw_token)
                self.assertFalse(token.is_revoked)
                self.assertIsNone(session.revoked_at)
        self.db.flush.assert_not_called()
        self.db.add.assert_not_called()

    def test_active_check_requires_current_session_and_active_owner(self):
        for row, active in (
            (self.session_row(), True), (self.session_row(revoked_at=self.now), False),
            (self.session_row(expires_at=self.now), False), (None, False),
        ):
            with self.subTest(active=active):
                self.db.scalar.return_value = row
                self.assertEqual(self.service.is_session_active(self.session_id, user_id=self.user_id), active)
                sql = self.pg_sql(self.db.scalar.call_args.args[0])
                self.assertIn("users.account_status =", sql)
                self.assertIn("auth_sessions.user_id =", sql)

    def test_logout_serializes_with_rotation_and_is_idempotent(self):
        session = self.session_row()
        self.db.scalar.return_value = session
        self.assertTrue(self.service.revoke_session(self.session_id, user_id=self.user_id))
        self.assertTrue(self.service.revoke_session(self.session_id, user_id=self.user_id))
        self.assertEqual(session.revoked_at, self.now)
        self.assertEqual(self.db.execute.call_count, 1)
        self.assertNotIn("consumed_at", self.pg_sql(self.db.execute.call_args.args[0]))
        for call in self.db.scalar.call_args_list:
            self.assertIn("FOR UPDATE", self.pg_sql(call.args[0]))

    def test_cross_user_token_cannot_trigger_rotation_or_revocation(self):
        self.db.execute.return_value.one_or_none.return_value = (self.session_id, self.user_id)
        with self.assertRaises(InvalidSessionError):
            self.service.rotate_refresh_token(self.raw_token, expected_user_id=uuid4())
        self.db.scalar.assert_not_called()
        self.db.add.assert_not_called()
        self.assertEqual(self.db.execute.call_count, 1)

    def test_logout_scopes_the_lock_to_the_requesting_user(self):
        other_user = uuid4()
        self.db.scalar.return_value = None
        self.assertFalse(self.service.revoke_session(self.session_id, user_id=other_user))
        statement = self.db.scalar.call_args.args[0]
        self.assertIn("auth_sessions.user_id =", self.pg_sql(statement))
        self.assertIn(other_user, statement.compile().params.values())
        self.db.execute.assert_not_called()

    def test_replacement_failure_exits_transaction_with_error_and_redacts_it(self):
        session, previous = self.session_row(), self.token_row()
        self.configure_rotation(session, previous)
        error = SQLAlchemyError(f"Driver details: {self.raw_token} {previous.token_hash}")
        self.db.add.side_effect = error

        def rollback(exc_type, exc, traceback):
            self.assertIs(exc, error)
            self.assertTrue(previous.is_revoked)
            previous.is_revoked = False
            previous.consumed_at = None
            return False

        self.transaction.__exit__.side_effect = rollback
        with self.assertRaises(SessionStoreError) as caught:
            self.service.rotate_refresh_token(self.raw_token)
        self.assertEqual(str(caught.exception), "Authentication session storage failed.")
        self.assertTrue(caught.exception.__suppress_context__)
        self.assertFalse(previous.is_revoked)
        self.assertIsNone(previous.consumed_at)

    def test_concurrent_refresh_rereads_after_lock_and_revokes_replayed_session(self):
        first_session, first_token = self.session_row(), self.token_row()
        self.configure_rotation(first_session, first_token)
        second_db, second_transaction = self.mock_transaction()
        second_session = self.session_row()
        second_db.execute.return_value.one_or_none.return_value = (self.session_id, self.user_id)
        self.factory.begin.side_effect = [self.transaction, second_transaction]
        first_at_commit, second_waiting_for_lock, first_committed = Event(), Event(), Event()

        # Model a second PostgreSQL transaction waiting on the first one's session row lock.
        def commit_first(exc_type, exc, traceback):
            self.assertIsNone(exc)
            first_at_commit.set()
            self.assertTrue(second_waiting_for_lock.wait(timeout=5))
            first_committed.set()
            return False

        def query_second(statement):
            sql = self.pg_sql(statement)
            if "FOR SHARE" in sql:
                return True
            if "FOR UPDATE" in sql:
                second_waiting_for_lock.set()
                self.assertTrue(first_committed.wait(timeout=5))
                return second_session
            self.assertTrue(first_committed.is_set())
            self.assertIn("FROM refresh_tokens", sql)
            return self.token_row(consumed_at=first_token.consumed_at, is_revoked=first_token.is_revoked)

        self.transaction.__exit__.side_effect = commit_first
        second_db.scalar.side_effect = query_second
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(self.service.rotate_refresh_token, self.raw_token)
            self.assertTrue(first_at_commit.wait(timeout=5))
            second = workers.submit(self.service.rotate_refresh_token, self.raw_token)
            self.assertEqual(first.result(timeout=5).session_id, self.session_id)
            with self.assertRaises(InvalidSessionError):
                second.result(timeout=5)

        self.db.add.assert_called_once()
        second_db.add.assert_not_called()
        self.assertEqual(second_session.revoked_at, self.now)
        self.assertEqual(second_db.execute.call_count, 2)
        second_transaction.__exit__.assert_called_once_with(None, None, None)

    def test_malformed_and_unknown_tokens_return_generic_error(self):
        with self.assertRaisesRegex(InvalidSessionError, r"^Invalid authentication session\.$"):
            self.service.rotate_refresh_token("malformed")
        self.factory.begin.assert_not_called()

        self.db.execute.return_value.one_or_none.return_value = None
        with self.assertRaisesRegex(InvalidSessionError, r"^Invalid authentication session\.$"):
            self.service.rotate_refresh_token(self.raw_token)
        self.db.scalar.assert_not_called()
        self.db.add.assert_not_called()
