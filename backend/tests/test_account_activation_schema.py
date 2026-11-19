import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable

from app.core.config import Settings
from app.core.passwords import hash_password
from app.models import AccountActionPurpose, AccountActionToken, AccountStatus, User, UserRole


class AccountActivationModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_hash = hash_password("isolated synthetic fixture password")

    def setUp(self):
        engine = sa.create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        self.db = self.enterContext(engine.connect())
        self.db.exec_driver_sql("PRAGMA foreign_keys = ON")
        User.metadata.create_all(self.db, tables=[User.__table__, AccountActionToken.__table__])
        self.users = User.__table__
        self.tokens = AccountActionToken.__table__
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.user_id = self.insert_user()

    def insert_user(self, **changes):
        values = {
            "id": uuid4(), "email": "sample@example.com", "role": UserRole.STUDENT,
            "created_at": self.now, "updated_at": self.now,
        }
        values.update(changes)
        self.db.execute(self.users.insert().values(**values))
        return values["id"]

    def insert_action(self, **changes):
        values = {
            "id": uuid4(), "user_id": self.user_id, "purpose": AccountActionPurpose.ACTIVATION,
            "token_digest": bytes(32), "auth_version": 0,
            "created_at": self.now, "expires_at": self.now + timedelta(hours=24),
        }
        self.db.execute(self.tokens.insert().values(**(values | changes)))

    def test_pending_default_and_active_flag_are_derived_from_status(self):
        statement = sa.select(self.users.c.account_status, self.users.c.is_active, self.users.c.auth_version)
        self.assertEqual(self.db.execute(statement).one(), (AccountStatus.PENDING_ACTIVATION, False, 0))
        self.db.execute(self.users.update().values(account_status=AccountStatus.ACTIVE,
                                                   hashed_password=self.fixture_hash, auth_version=1))
        self.assertEqual(self.db.execute(statement).one(), (AccountStatus.ACTIVE, True, 1))
        self.db.execute(self.users.update().values(account_status=AccountStatus.DISABLED))
        self.assertEqual(self.db.execute(statement).one(), (AccountStatus.DISABLED, False, 1))

    def test_account_constraints_reject_missing_malformed_or_inconsistent_credentials(self):
        for values in (
            {"account_status": AccountStatus.ACTIVE},
            {"account_status": AccountStatus.ACTIVE, "hashed_password": "malformed"},
            {"account_status": AccountStatus.PENDING_ACTIVATION, "hashed_password": self.fixture_hash},
            {"account_status": "UNKNOWN"},
            {"auth_version": -1},
        ):
            with self.assertRaises(sa.exc.IntegrityError), self.db.begin_nested():
                self.db.execute(self.users.update().values(**values))

    def test_action_digest_owner_purpose_version_and_time_constraints(self):
        for values in (
            {"user_id": uuid4()},
            {"purpose": "UNKNOWN"},
            {"token_digest": bytes(31)},
            {"auth_version": -1},
            {"expires_at": self.now},
            {"consumed_at": self.now - timedelta(seconds=1)},
            {"consumed_at": self.now + timedelta(hours=24)},
            {"invalidated_at": self.now - timedelta(seconds=1)},
            {"consumed_at": self.now, "invalidated_at": self.now},
        ):
            with self.assertRaises(sa.exc.IntegrityError), self.db.begin_nested():
                self.insert_action(**values)

    def test_one_outstanding_action_per_purpose_and_globally_unique_digest(self):
        self.insert_action()
        with self.assertRaises(sa.exc.IntegrityError), self.db.begin_nested():
            self.insert_action(token_digest=bytes([1]) * 32)
        with self.assertRaises(sa.exc.IntegrityError), self.db.begin_nested():
            self.insert_action(purpose=AccountActionPurpose.PASSWORD_RESET)
        self.insert_action(purpose=AccountActionPurpose.PASSWORD_RESET, token_digest=bytes([2]) * 32)
        self.db.execute(self.tokens.update().where(
            self.tokens.c.purpose == AccountActionPurpose.ACTIVATION,
        ).values(invalidated_at=self.now))
        self.insert_action(token_digest=bytes([1]) * 32, auth_version=1)

    def test_action_relationship_and_cascading_ownership(self):
        self.insert_action()
        with sessionmaker(bind=self.db)() as db:
            self.assertEqual(len(db.get(User, self.user_id).account_action_tokens), 1)
        self.db.execute(self.users.delete())
        self.assertEqual(self.db.scalar(sa.select(sa.func.count()).select_from(self.tokens)), 0)

    def test_invitation_lifetime_is_configurable_and_positive(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(Settings(_env_file=None).AUTH_INVITATION_LIFETIME_HOURS, 24)
            with patch.dict("os.environ", {"AUTH_INVITATION_LIFETIME_HOURS": "12"}):
                self.assertEqual(Settings(_env_file=None).AUTH_INVITATION_LIFETIME_HOURS, 12)
            with self.assertRaises(ValueError):
                Settings(_env_file=None, AUTH_INVITATION_LIFETIME_HOURS=0)


class AccountActivationMigrationTests(unittest.TestCase):
    backend = Path(__file__).resolve().parents[1]
    revision = "0003_account_activation"
    parent = "0002_auth_sessions"

    @classmethod
    def setUpClass(cls):
        cls.sql = cls.render(command.upgrade, f"{cls.parent}:{cls.revision}")
        cls.downgrade = cls.render(command.downgrade, f"{cls.revision}:{cls.parent}")

    @classmethod
    def config(cls, output=None):
        config = Config(output_buffer=output)
        config.set_main_option("script_location", str(cls.backend / "alembic"))
        return config

    @classmethod
    def render(cls, command_method, revisions):
        output = StringIO()
        with (
            patch("app.core.config.settings.DATABASE_URL", "postgresql+pg8000://localhost/campus_od_offline"),
            patch("pg8000.dbapi.connect", side_effect=AssertionError("Offline migration tests cannot connect")),
        ):
            command_method(cls.config(output), revisions, sql=True)
        return " ".join(output.getvalue().split())

    def test_revision_and_backfill_preserve_legacy_account_state(self):
        scripts = ScriptDirectory.from_config(self.config())
        self.assertEqual(scripts.get_current_head(), self.revision)
        self.assertEqual(scripts.get_revision(self.revision).down_revision, self.parent)
        steps = (
            "CREATE TYPE public.account_status_enum AS ENUM ('PENDING_ACTIVATION', 'ACTIVE', 'DISABLED')",
            "ALTER TABLE public.users ADD COLUMN account_status public.account_status_enum",
            "UPDATE public.users SET account_status = CASE WHEN is_active THEN 'ACTIVE'::public.account_status_enum "
            "ELSE 'DISABLED'::public.account_status_enum END",
            "Migration 0003 requires Argon2id PHC hashes for existing active accounts",
            "ALTER COLUMN account_status SET DEFAULT 'PENDING_ACTIVATION'",
            "ALTER TABLE public.users DROP COLUMN is_active",
            "GENERATED ALWAYS AS (account_status = 'ACTIVE') STORED NOT NULL",
        )
        positions = [self.sql.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("UPDATE public.auth_sessions", self.sql)
        self.assertNotIn("UPDATE public.refresh_tokens", self.sql)
        self.assertNotIn("SET hashed_password", self.sql)

    def test_postgresql_types_constraints_and_indexes_match_metadata(self):
        dialect = postgresql.dialect()
        self.assertIn("CREATE TYPE public.account_action_purpose_enum AS ENUM ('ACTIVATION', 'PASSWORD_RESET')", self.sql)
        self.assertIn("ALTER COLUMN hashed_password DROP NOT NULL", self.sql)
        self.assertIn("auth_version INTEGER DEFAULT 0 NOT NULL", self.sql)
        self.assertIn("token_digest BYTEA NOT NULL", self.sql)
        self.assertIn("FOREIGN KEY(user_id) REFERENCES public.users (id) ON DELETE CASCADE", self.sql)
        for model in (User, AccountActionToken):
            model_sql = " ".join(str(CreateTable(model.__table__).compile(dialect=dialect)).split())
            for constraint in model.__table__.constraints:
                if isinstance(constraint, (sa.CheckConstraint, sa.UniqueConstraint)) and constraint.name:
                    fragment = f"CONSTRAINT {constraint.name}"
                    offset = model_sql.find(fragment)
                    if offset >= 0:
                        definition = " ".join(dialect.ddl_compiler(dialect, None).process(constraint).split())
                        self.assertIn(definition, self.sql)
        for index in AccountActionToken.__table__.indexes:
            definition = str(CreateIndex(index).compile(dialect=dialect)).replace(
                " ON account_action_tokens ", " ON public.account_action_tokens ",
            )
            self.assertIn(definition, self.sql)

    def test_private_table_acl_and_downgrade_guards(self):
        for sql in (
            "ALTER TABLE public.account_action_tokens ENABLE ROW LEVEL SECURITY",
            "REVOKE ALL PRIVILEGES ON TABLE public.account_action_tokens FROM PUBLIC",
            "REVOKE ALL PRIVILEGES ON TABLE public.account_action_tokens FROM %I",
            "rolname IN ('anon', 'authenticated')",
            "aclexplode(a.attacl)",
            "has_table_privilege",
            "has_any_column_privilege",
            "RAISE EXCEPTION",
        ):
            self.assertIn(sql, self.sql)
        self.assertNotIn("CREATE POLICY", self.sql)
        self.assertNotIn("INSERT INTO public.account_action_tokens", self.sql)
        self.assertLess(self.downgrade.index("Cannot downgrade 0003"), self.downgrade.index("DROP TABLE"))
        self.assertIn("ALTER COLUMN is_active DROP EXPRESSION", self.downgrade)
