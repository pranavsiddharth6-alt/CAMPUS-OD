"""Add revocable authentication sessions and refresh-token rotation state."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0002_auth_sessions"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("timezone('UTC', now())"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("id", "user_id", name="uq_auth_sessions_id_user_id"),
        sa.CheckConstraint("expires_at >= created_at", name="ck_auth_sessions_expiry_order"),
        sa.CheckConstraint("revoked_at >= created_at", name="ck_auth_sessions_revocation_order"),
        schema="public",
    )
    op.execute("ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE public.auth_sessions FROM PUBLIC")
    op.execute("""
        DO $auth_session_access$
        DECLARE
            client_role text;
            table_privileges text := 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER';
        BEGIN
            IF current_setting('server_version_num')::integer >= 170000 THEN
                table_privileges := table_privileges || ', MAINTAIN';
            END IF;

            FOR client_role IN SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN ('anon', 'authenticated')
            LOOP
                EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.auth_sessions FROM %I', client_role);
            END LOOP;

            SELECT rolname INTO client_role FROM pg_catalog.pg_roles
            WHERE rolname IN ('anon', 'authenticated')
              AND (has_table_privilege(oid, 'public.auth_sessions'::regclass, table_privileges)
                   OR has_any_column_privilege(oid, 'public.auth_sessions'::regclass, 'SELECT, INSERT, UPDATE, REFERENCES'))
            LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Role % still has privileges on public.auth_sessions', client_role;
            END IF;
        END;
        $auth_session_access$
    """)
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], schema="public")
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], schema="public")

    op.add_column("refresh_tokens", sa.Column("session_id", postgresql.UUID(as_uuid=True)), schema="public")
    op.add_column("refresh_tokens", sa.Column("consumed_at", sa.DateTime()), schema="public")

    # Legacy tokens have no known rotation history. Keep their records and attach them to revoked sessions.
    op.execute("""
        INSERT INTO public.auth_sessions (id, user_id, created_at, expires_at, revoked_at)
        SELECT id, user_id, created_at, GREATEST(expires_at, created_at),
               GREATEST(created_at, timezone('UTC', now()))
        FROM public.refresh_tokens
    """)
    op.execute("UPDATE public.refresh_tokens SET session_id = id WHERE session_id IS NULL")

    op.alter_column("refresh_tokens", "session_id", nullable=False, schema="public")
    op.create_foreign_key(
        "fk_refresh_tokens_session_owner", "refresh_tokens", "auth_sessions",
        ["session_id", "user_id"], ["id", "user_id"],
        source_schema="public", referent_schema="public", ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_refresh_tokens_consumption", "refresh_tokens",
        "consumed_at IS NULL OR (is_revoked AND consumed_at >= created_at AND consumed_at < expires_at)",
        schema="public",
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"], schema="public")
    op.create_index(
        "uq_refresh_tokens_one_unrevoked_per_session", "refresh_tokens", ["session_id"],
        unique=True, postgresql_where=sa.text("is_revoked IS FALSE"), schema="public",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE public.refresh_tokens, public.auth_sessions IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $auth_session_downgrade$
        BEGIN
            IF EXISTS (SELECT 1 FROM public.auth_sessions) THEN
                RAISE EXCEPTION 'Cannot downgrade while authentication session records exist';
            END IF;
        END;
        $auth_session_downgrade$
    """)
    op.drop_index("uq_refresh_tokens_one_unrevoked_per_session", table_name="refresh_tokens", schema="public")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens", schema="public")
    op.drop_constraint("ck_refresh_tokens_consumption", "refresh_tokens", type_="check", schema="public")
    op.drop_constraint("fk_refresh_tokens_session_owner", "refresh_tokens", type_="foreignkey", schema="public")
    op.drop_column("refresh_tokens", "consumed_at", schema="public")
    op.drop_column("refresh_tokens", "session_id", schema="public")
    op.drop_table("auth_sessions", schema="public")
