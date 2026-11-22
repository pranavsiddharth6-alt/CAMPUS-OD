"""Add department-scoped HOD assignments and application review states."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_hod_approval"
down_revision = "0003_account_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE public.user_role_enum ADD VALUE IF NOT EXISTS 'HOD'")
    for value in ("UNDER_HOD_REVIEW", "HOD_CORRECTION_REQUESTED", "UNDER_TUTOR_CORRECTION_REVIEW"):
        op.execute(f"ALTER TYPE public.application_status_enum ADD VALUE IF NOT EXISTS '{value}'")

    op.add_column("od_applications", sa.Column("department_id", postgresql.UUID(as_uuid=True)), schema="public")
    op.create_foreign_key("fk_od_applications_department", "od_applications", "departments",
                          ["department_id"], ["id"], source_schema="public", referent_schema="public",
                          ondelete="RESTRICT")
    op.execute("""
        UPDATE public.od_applications AS application
        SET department_id = student.department_id
        FROM public.student_profiles AS student
        WHERE student.id = application.student_id
    """)
    op.create_index("ix_od_applications_department_id", "od_applications", ["department_id"], schema="public")

    op.create_table(
        "hod_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.departments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime()),
        sa.Column("ended_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("public.users.id", ondelete="RESTRICT")),
        sa.CheckConstraint(
            "(ended_at IS NULL AND ended_by_user_id IS NULL) OR "
            "(ended_at >= assigned_at AND ended_at IS NOT NULL AND ended_by_user_id IS NOT NULL)",
            name="ck_hod_assignment_end",
        ),
        schema="public",
    )
    for column in ("department_id", "user_id"):
        op.create_index(f"ix_hod_assignments_{column}", "hod_assignments", [column], schema="public")
    for name, column in (("department", "department_id"), ("user", "user_id")):
        op.create_index(f"uq_hod_active_{name}", "hod_assignments", [column], unique=True,
                        postgresql_where=sa.text("ended_at IS NULL"), schema="public")
    op.add_column("application_status_history", sa.Column("hod_assignment_id", postgresql.UUID(as_uuid=True)),
                  schema="public")
    op.create_foreign_key("fk_status_history_hod_assignment", "application_status_history", "hod_assignments",
                          ["hod_assignment_id"], ["id"], source_schema="public", referent_schema="public",
                          ondelete="RESTRICT")
    op.execute("ALTER TABLE public.hod_assignments ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE public.hod_assignments FROM PUBLIC")
    op.execute("""
        DO $hod_grants$
        DECLARE client_role text;
        BEGIN
            FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
            LOOP
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = client_role) THEN
                    EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.hod_assignments FROM %I', client_role);
                END IF;
            END LOOP;
        END;
        $hod_grants$
    """)


    op.execute("""
        CREATE FUNCTION public.invalidate_sessions_after_identity_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path = '' AS $identity_change$
        BEGIN
            NEW.auth_version := GREATEST(NEW.auth_version, OLD.auth_version + 1);
            UPDATE public.refresh_tokens SET is_revoked = true
            WHERE user_id = OLD.id AND NOT is_revoked;
            UPDATE public.auth_sessions
            SET revoked_at = GREATEST(created_at, timezone('UTC', now()))
            WHERE user_id = OLD.id AND revoked_at IS NULL;
            RETURN NEW;
        END;
        $identity_change$
    """)
    op.execute("REVOKE ALL ON FUNCTION public.invalidate_sessions_after_identity_change() FROM PUBLIC")
    op.execute("""
        CREATE TRIGGER users_revoke_changed_identity_sessions
        BEFORE UPDATE OF role, account_status ON public.users
        FOR EACH ROW WHEN (OLD.role IS DISTINCT FROM NEW.role OR
                           (OLD.account_status = 'ACTIVE' AND NEW.account_status <> 'ACTIVE'))
        EXECUTE FUNCTION public.invalidate_sessions_after_identity_change()
    """)


def downgrade() -> None:
    raise RuntimeError("0004 preserves HOD decisions and assignments. Restore a verified backup to roll back.")
