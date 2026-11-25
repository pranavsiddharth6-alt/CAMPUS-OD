"""Add approved venue pins and verifiable independent GPS attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0006_map_od"
down_revision = "0005_admin_records"
branch_labels = None
depends_on = None


def upgrade():
    for axis, bounds in (("latitude", (-90, 90)), ("longitude", (-180, 180))):
        name = f"expected_venue_{axis}"
        op.add_column("od_applications", sa.Column(name, sa.Float()), schema="public")
        op.create_check_constraint(f"ck_od_venue_{axis}", "od_applications",
                                   f"{name} BETWEEN {bounds[0]} AND {bounds[1]}", schema="public")
    op.add_column("evidence_submissions", sa.Column(
        "is_location_draft", sa.Boolean(), server_default=sa.false(), nullable=False,
    ), schema="public")
    op.add_column("evidence_submissions", sa.Column("map_capture_id", sa.Uuid()), schema="public")
    op.create_foreign_key("fk_evidence_map_capture", "evidence_submissions", "location_captures",
                          ["map_capture_id"], ["id"], ondelete="RESTRICT",
                          source_schema="public", referent_schema="public")
    op.create_index("uq_event_day_location_draft", "evidence_submissions", ["event_day_id"], unique=True,
                    postgresql_where=sa.text("is_location_draft IS TRUE"), schema="public")
    for name in ("distance_metres", "allowed_radius_metres", "allowed_accuracy_metres"):
        op.add_column("location_captures", sa.Column(name, sa.Float()), schema="public")
    op.add_column("location_captures", sa.Column("verification_result", sa.String(32)), schema="public")
    op.add_column("location_captures", sa.Column("browser_time_present", sa.Boolean()), schema="public")
    op.add_column("location_captures", sa.Column("request_key", sa.String(36)), schema="public")
    op.create_index("ix_location_captures_request_key", "location_captures", ["request_key"],
                    unique=True, schema="public")


def downgrade():
    raise RuntimeError("Restore a verified backup to roll back without losing Map OD evidence.")
