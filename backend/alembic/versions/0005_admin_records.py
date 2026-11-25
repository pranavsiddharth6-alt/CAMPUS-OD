"""Add student demographics, record activity and administrative audit history."""

import sqlalchemy as sa
from alembic import op

revision = "0005_admin_records"
down_revision = "0004_hod_approval"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("hod_display_name", sa.String(150)), schema="public")
    op.add_column("student_profiles", sa.Column("gender", sa.String(6)), schema="public")
    op.add_column("student_profiles", sa.Column("accommodation", sa.String(15)), schema="public")
    op.create_check_constraint("ck_student_gender", "student_profiles",
                               "gender IN ('MALE', 'FEMALE')", schema="public")
    op.create_check_constraint("ck_student_accommodation", "student_profiles",
                               "accommodation IN ('COLLEGE_HOSTEL', 'OUTSIDE_STAYING', 'GUARDIAN', 'OTHER')",
                               schema="public")
    for table in ("departments", "classes"):
        op.add_column(table, sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
                      schema="public")
    op.create_table(
        "admin_audit",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("public.users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        schema="public",
    )
    op.execute("ALTER TABLE public.admin_audit ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON TABLE public.admin_audit FROM PUBLIC")
    op.execute("""
        DO $grants$
        DECLARE client_role text;
        BEGIN
            FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
            LOOP
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = client_role) THEN
                    EXECUTE format('REVOKE ALL ON TABLE public.admin_audit FROM %I', client_role);
                END IF;
            END LOOP;
        END;
        $grants$
    """)


def downgrade():
    raise RuntimeError("Restore a verified backup to roll back without dropping administrative data.")
