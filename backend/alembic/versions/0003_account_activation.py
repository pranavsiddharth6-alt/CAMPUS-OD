"""Add account lifecycle state and private account-action credentials."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0003_account_activation"
down_revision = "0002_auth_sessions"
branch_labels = None
depends_on = None

_account_status = postgresql.ENUM(
    "PENDING_ACTIVATION", "ACTIVE", "DISABLED", name="account_status_enum", schema="public", create_type=False,
)
_action_purpose = postgresql.ENUM(
    "ACTIVATION", "PASSWORD_RESET", name="account_action_purpose_enum", schema="public", create_type=False,
)
_active_hash_constraint = (
    "account_status != 'ACTIVE' OR hashed_password IS NOT NULL AND hashed_password ~ "
    "'^[$]argon2id[$]v=19[$]m=[1-9][0-9]*,t=[1-9][0-9]*,p=[1-9][0-9]*"
    "[$][A-Za-z0-9+/]+[$][A-Za-z0-9+/]+$'"
)


def _restrict_action_token_access() -> None:
    op.execute("ALTER TABLE public.account_action_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE public.account_action_tokens FROM PUBLIC")
    op.execute("""
        DO $account_action_access$
        DECLARE
            token_table regclass := 'public.account_action_tokens'::regclass;
            client_role text;
            table_privileges text := 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER';
        BEGIN
            IF current_setting('server_version_num')::integer >= 170000 THEN
                table_privileges := table_privileges || ', MAINTAIN';
            END IF;

            FOR client_role IN SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN ('anon', 'authenticated')
            LOOP
                EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.account_action_tokens FROM %I', client_role);
            END LOOP;

            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_class c
                CROSS JOIN LATERAL pg_catalog.aclexplode(c.relacl) acl
                WHERE c.oid = token_table AND acl.grantee = 0
            ) OR EXISTS (
                SELECT 1 FROM pg_catalog.pg_attribute a
                CROSS JOIN LATERAL pg_catalog.aclexplode(a.attacl) acl
                WHERE a.attrelid = token_table AND acl.grantee = 0
            ) THEN
                RAISE EXCEPTION 'PUBLIC still has privileges on public.account_action_tokens';
            END IF;

            SELECT rolname INTO client_role FROM pg_catalog.pg_roles
            WHERE rolname IN ('anon', 'authenticated')
              AND (has_table_privilege(oid, token_table, table_privileges)
                   OR has_any_column_privilege(oid, token_table, 'SELECT, INSERT, UPDATE, REFERENCES'))
            LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Role % still has privileges on public.account_action_tokens', client_role;
            END IF;
        END;
        $account_action_access$
    """)


def upgrade() -> None:
    bind = op.get_bind()
    _account_status.create(bind, checkfirst=False)
    _action_purpose.create(bind, checkfirst=False)

    op.add_column("users", sa.Column("account_status", _account_status), schema="public")
    op.execute("""
        UPDATE public.users
        SET account_status = CASE
            WHEN is_active THEN 'ACTIVE'::public.account_status_enum
            ELSE 'DISABLED'::public.account_status_enum
        END
    """)
    # Fail with a generic message before any constraint can report a failing row.
    op.execute(f"""
        DO $account_hash_check$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.users WHERE NOT ({_active_hash_constraint})) THEN
                RAISE EXCEPTION 'Migration 0003 requires Argon2id PHC hashes for existing active accounts';
            END IF;
        END;
        $account_hash_check$
    """)
    op.alter_column(
        "users", "account_status", nullable=False, server_default=sa.text("'PENDING_ACTIVATION'"), schema="public",
    )
    op.add_column(
        "users", sa.Column("auth_version", sa.Integer(), server_default=sa.text("0"), nullable=False), schema="public",
    )
    op.alter_column("users", "hashed_password", nullable=True, schema="public")
    op.create_check_constraint("ck_users_active_password_hash", "users", _active_hash_constraint, schema="public")
    op.create_check_constraint(
        "ck_users_pending_without_password", "users",
        "account_status <> 'PENDING_ACTIVATION' OR hashed_password IS NULL", schema="public",
    )
    op.create_check_constraint("ck_users_auth_version", "users", "auth_version >= 0", schema="public")

    op.drop_column("users", "is_active", schema="public")
    op.add_column(
        "users", sa.Column("is_active", sa.Boolean(), sa.Computed("account_status = 'ACTIVE'", persisted=True),
                           nullable=False),
        schema="public",
    )

    op.create_table(
        "account_action_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("public.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", _action_purpose, nullable=False),
        sa.Column("token_digest", sa.LargeBinary(32), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_digest", name="uq_account_action_tokens_digest"),
        sa.CheckConstraint("length(token_digest) = 32", name="ck_account_action_tokens_digest_length"),
        sa.CheckConstraint("auth_version >= 0", name="ck_account_action_tokens_auth_version"),
        sa.CheckConstraint("expires_at > created_at", name="ck_account_action_tokens_expiry"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at < expires_at AND invalidated_at IS NULL)",
            name="ck_account_action_tokens_consumption",
        ),
        sa.CheckConstraint(
            "invalidated_at IS NULL OR invalidated_at >= created_at", name="ck_account_action_tokens_invalidation",
        ),
        schema="public",
    )
    _restrict_action_token_access()
    op.create_index("ix_account_action_tokens_user_id", "account_action_tokens", ["user_id"], schema="public")
    op.create_index("ix_account_action_tokens_expires_at", "account_action_tokens", ["expires_at"], schema="public")
    op.create_index(
        "uq_account_action_tokens_outstanding", "account_action_tokens", ["user_id", "purpose"], unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND invalidated_at IS NULL"), schema="public",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE public.users, public.account_action_tokens IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $account_downgrade_check$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM public.users
                WHERE account_status = 'PENDING_ACTIVATION' OR hashed_password IS NULL OR auth_version <> 0
            ) OR EXISTS (SELECT 1 FROM public.account_action_tokens) THEN
                RAISE EXCEPTION 'Cannot downgrade 0003 after account lifecycle data has been created';
            END IF;
        END;
        $account_downgrade_check$
    """)
    op.drop_table("account_action_tokens", schema="public")
    op.execute("ALTER TABLE public.users ALTER COLUMN is_active DROP EXPRESSION")
    op.alter_column("users", "is_active", server_default=sa.text("true"), schema="public")
    op.alter_column("users", "hashed_password", nullable=False, schema="public")
    for constraint in ("ck_users_active_password_hash", "ck_users_pending_without_password", "ck_users_auth_version"):
        op.drop_constraint(constraint, "users", type_="check", schema="public")
    op.drop_column("users", "auth_version", schema="public")
    op.drop_column("users", "account_status", schema="public")
    _action_purpose.drop(op.get_bind(), checkfirst=False)
    _account_status.drop(op.get_bind(), checkfirst=False)
