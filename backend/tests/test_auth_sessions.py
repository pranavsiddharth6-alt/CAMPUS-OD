import re
import unittest
import warnings
from datetime import datetime, timedelta
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.passwords import hash_password
from app.models import AccountStatus, AuthSession, RefreshToken, User, UserRole


class AuthSessionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_hash = hash_password("isolated synthetic fixture password")

    def setUp(self):
        # Isolate constraint behavior without connecting to PostgreSQL.
        metadata = sa.MetaData()
        for model in (User, AuthSession, RefreshToken):
            model.__table__.to_metadata(metadata)
        self.sessions = metadata.tables["auth_sessions"]
        self.tokens = metadata.tables["refresh_tokens"]
        for index in self.tokens.indexes:
            predicate = index.dialect_options["postgresql"].get("where")
            if predicate is not None:
                index.dialect_options["sqlite"]["where"] = predicate

        engine = sa.create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.connection = engine.connect()
        self.addCleanup(self.connection.close)
        self.connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        metadata.create_all(self.connection)

        self.created = datetime(2026, 1, 1, 12)
        self.expires = self.created + timedelta(days=1)
        self.owner, self.other_user = uuid4(), uuid4()
        self.connection.execute(
            metadata.tables["users"].insert(),
            [
                {
                    "id": user_id, "email": email, "role": UserRole.STUDENT,
                    "account_status": AccountStatus.ACTIVE, "hashed_password": self.fixture_hash,
                    "created_at": self.created, "updated_at": self.created,
                }
                for user_id, email in ((self.owner, "first@example.com"), (self.other_user, "second@example.com"))
            ],
        )
        self.session_id = uuid4()
        self.connection.execute(self.sessions.insert().values(
            id=self.session_id, user_id=self.owner, created_at=self.created, expires_at=self.expires,
        ))

    def insert_token(self, label, **overrides):
        values = {
            "id": uuid4(), "session_id": self.session_id, "user_id": self.owner,
            "token_hash": sha256(label.encode()).hexdigest(), "created_at": self.created,
            "expires_at": self.expires,
        }
        values.update(overrides)
        self.connection.execute(self.tokens.insert().values(**values))
        return values["id"]

    def test_relationships_synchronize_without_overlapping_owner_writes(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", sa.exc.SAWarning)
            configure_mappers()
        relationships = sa.inspect(RefreshToken).relationships
        self.assertEqual(relationships.auth_session.mapper.class_, AuthSession)
        self.assertEqual(relationships.user.mapper.class_, User)
        self.assertEqual({destination.key for _, destination in relationships.auth_session.synchronize_pairs}, {"session_id"})
        self.assertEqual({destination.key for _, destination in relationships.user.synchronize_pairs}, {"user_id"})

    def test_session_expiry_and_revocation_cannot_precede_creation(self):
        earlier = self.created - timedelta(seconds=1)
        for changes in ({"expires_at": earlier}, {"revoked_at": earlier}):
            with self.subTest(fields=tuple(changes)):
                values = {"user_id": self.owner, "created_at": self.created, "expires_at": self.expires}
                values.update(changes)
                with self.assertRaisesRegex(sa.exc.IntegrityError, "CHECK constraint failed"):
                    self.connection.execute(self.sessions.insert().values(**values))

    def test_refresh_token_needs_a_session_with_the_same_owner(self):
        for changes in ({"user_id": self.other_user}, {"session_id": uuid4()}):
            with self.subTest(fields=tuple(changes)):
                with self.assertRaisesRegex(sa.exc.IntegrityError, "FOREIGN KEY constraint failed"):
                    self.insert_token("mismatch", **changes)
        with self.assertRaisesRegex(sa.exc.IntegrityError, "NOT NULL constraint failed"):
            self.insert_token("no session", session_id=None)

    def test_consumption_requires_revocation_and_an_unexpired_token(self):
        invalid_states = (
            {"consumed_at": self.created, "is_revoked": False},
            {"consumed_at": self.created - timedelta(seconds=1), "is_revoked": True},
            {"consumed_at": self.expires, "is_revoked": True},
        )
        for case, state in enumerate(invalid_states):
            with self.subTest(state=state):
                with self.assertRaisesRegex(sa.exc.IntegrityError, "CHECK constraint failed"):
                    self.insert_token(f"invalid consumption {case}", **state)

    def test_rotation_replaces_the_only_usable_token_and_retains_replay_history(self):
        original = self.insert_token("original")
        self.connection.commit()
        with self.assertRaisesRegex(sa.exc.IntegrityError, "UNIQUE constraint failed"):
            with self.connection.begin():
                self.insert_token("second current token")

        rotated_at = self.created + timedelta(minutes=1)
        with self.connection.begin():
            self.connection.execute(self.tokens.update().where(self.tokens.c.id == original).values(
                is_revoked=True, consumed_at=rotated_at,
            ))
            replacement = self.insert_token("replacement", created_at=rotated_at)

        with self.connection.begin():
            replay_lookup = sa.select(
                self.tokens.c.id, self.tokens.c.is_revoked, self.tokens.c.consumed_at,
            ).where(self.tokens.c.token_hash == sha256(b"original").hexdigest())
            replay = self.connection.execute(replay_lookup).one()
            self.assertEqual(tuple(replay), (original, True, rotated_at))

            usable = self.connection.scalars(sa.select(self.tokens.c.id).where(
                self.tokens.c.session_id == self.session_id,
                self.tokens.c.is_revoked.is_(False),
                self.tokens.c.consumed_at.is_(None),
                self.tokens.c.expires_at > rotated_at,
            )).all()
            self.assertEqual(usable, [replacement])
            self.assertIsNone(self.connection.scalar(sa.select(self.sessions.c.revoked_at)))

        with self.assertRaisesRegex(sa.exc.IntegrityError, "UNIQUE constraint failed"):
            with self.connection.begin():
                self.insert_token("third current token", created_at=rotated_at)

    def test_logout_revokes_an_unconsumed_token_without_a_rotation_marker(self):
        token_id = self.insert_token("logout")
        revoked_at = self.created + timedelta(minutes=1)
        self.connection.execute(self.sessions.update().where(self.sessions.c.id == self.session_id).values(
            revoked_at=revoked_at,
        ))
        self.connection.execute(self.tokens.update().where(self.tokens.c.id == token_id).values(is_revoked=True))

        result = self.connection.execute(sa.select(self.tokens.c.is_revoked, self.tokens.c.consumed_at)).one()
        self.assertEqual(tuple(result), (True, None))
        self.assertEqual(self.connection.scalar(sa.select(self.sessions.c.revoked_at)), revoked_at)


class AuthSessionMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        output = StringIO()
        cls.config = Config(output_buffer=output)
        cls.config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
        with (
            patch("app.core.config.settings.DATABASE_URL", "postgresql+pg8000://offline.invalid/postgres"),
            patch("pg8000.dbapi.connect", side_effect=AssertionError("Offline tests cannot connect to PostgreSQL")),
        ):
            command.upgrade(cls.config, "0001_initial_schema:0002_auth_sessions", sql=True)
        cls.sql = output.getvalue()

    def test_revision_preserves_initial_migration_as_parent(self):
        scripts = ScriptDirectory.from_config(self.config)
        self.assertEqual(scripts.get_revision("0002_auth_sessions").down_revision, "0001_initial_schema")
        self.assertEqual(re.findall(r"(?m)^CREATE TABLE ([\w.]+)", self.sql), ["public.auth_sessions"])
        self.assertIn("UPDATE public.alembic_version SET version_num='0002_auth_sessions'", self.sql)

    def test_session_ddl_constraints_and_indexes_match_models(self):
        def normalize(sql):
            return " ".join(sql.replace("public.", "").split())

        dialect = postgresql.dialect()
        sql = normalize(self.sql)
        self.assertIn(normalize(str(CreateTable(AuthSession.__table__).compile(dialect=dialect))), sql)
        ddl_compiler = dialect.ddl_compiler(dialect, None)
        for constraint in RefreshToken.__table__.constraints:
            if constraint.name in {"fk_refresh_tokens_session_owner", "ck_refresh_tokens_consumption"}:
                constraint_sql = ddl_compiler.process(constraint)
                self.assertIn(normalize(f"ALTER TABLE refresh_tokens ADD {constraint_sql}"), sql)
        for model in (AuthSession, RefreshToken):
            for index in model.__table__.indexes:
                if "session_id" in index.columns or model is AuthSession:
                    self.assertIn(normalize(str(CreateIndex(index).compile(dialect=dialect))), sql)
        self.assertFalse(RefreshToken.__table__.c.session_id.nullable)
        self.assertTrue(RefreshToken.__table__.c.consumed_at.nullable)
        self.assertIn("ALTER TABLE refresh_tokens ADD COLUMN consumed_at TIMESTAMP WITHOUT TIME ZONE;", sql)

    def test_backfill_keeps_legacy_fields_and_links_only_revoked_sessions(self):
        sql = " ".join(self.sql.split())
        steps = (
            "ALTER TABLE public.refresh_tokens ADD COLUMN session_id UUID",
            "INSERT INTO public.auth_sessions (id, user_id, created_at, expires_at, revoked_at) "
            "SELECT id, user_id, created_at, GREATEST(expires_at, created_at), "
            "GREATEST(created_at, timezone('UTC', now())) FROM public.refresh_tokens",
            "UPDATE public.refresh_tokens SET session_id = id WHERE session_id IS NULL",
            "ALTER TABLE public.refresh_tokens ALTER COLUMN session_id SET NOT NULL",
        )
        order = [sql.index(step) for step in steps]
        self.assertEqual(order, sorted(order))
        self.assertEqual(
            re.findall(r"(?im)^UPDATE public\.refresh_tokens[^;]*", self.sql),
            ["UPDATE public.refresh_tokens SET session_id = id WHERE session_id IS NULL"],
        )
        self.assertNotRegex(self.sql, r"(?im)^\s*(DROP|TRUNCATE|DELETE FROM)\b")

    def test_sql_keeps_sessions_private(self):
        rls = "ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY"
        self.assertIn(rls, self.sql)
        self.assertIn("REVOKE ALL PRIVILEGES ON TABLE public.auth_sessions FROM PUBLIC", self.sql)
        self.assertIn("REVOKE ALL PRIVILEGES ON TABLE public.auth_sessions FROM %I", self.sql)
        self.assertIn("rolname IN ('anon', 'authenticated')", self.sql)
        self.assertIn("has_table_privilege", self.sql)
        self.assertIn("has_any_column_privilege", self.sql)
        self.assertIn("RAISE EXCEPTION", self.sql)
        self.assertLess(self.sql.index(rls), self.sql.index("INSERT INTO public.auth_sessions"))
        self.assertNotRegex(self.sql, r"(?im)^\s*(GRANT|CREATE POLICY|ALTER DEFAULT PRIVILEGES)\b")
        self.assertNotIn("DISABLE ROW LEVEL SECURITY", self.sql)
