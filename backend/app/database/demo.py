"""SQLite transaction adapter for the isolated, single-machine demo."""

from pathlib import Path

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


class DemoSession(Session):
    def connection(self, bind_arguments=None, execution_options=None):
        if execution_options == {"isolation_level": "READ COMMITTED"}:
            execution_options = None
        return super().connection(bind_arguments=bind_arguments, execution_options=execution_options)


def create_demo_engine(directory: Path):
    engine = create_engine(
        URL.create("sqlite", database=str(directory / "campus_od.sqlite3")), hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def connect(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys = ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        # SQLite lacks row locks. Serialize demo transactions before they read.
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def upgrade_demo_hod(engine):
    """Apply additive changes to an initialized SQLite demo in one transaction."""
    from app.models.academic import HODAssignment

    with engine.begin() as db:
        schema = inspect(db)
        HODAssignment.__table__.create(db, checkfirst=True)
        db.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS users_revoke_changed_identity_sessions
            AFTER UPDATE OF role, account_status ON users
            WHEN OLD.role <> NEW.role OR (OLD.account_status = 'ACTIVE' AND NEW.account_status <> 'ACTIVE')
            BEGIN
                UPDATE users SET auth_version = max(NEW.auth_version, OLD.auth_version + 1) WHERE id = OLD.id;
                UPDATE refresh_tokens SET is_revoked = 1 WHERE user_id = OLD.id AND is_revoked = 0;
                UPDATE auth_sessions
                SET revoked_at = max(created_at, strftime('%Y-%m-%d %H:%M:%f', 'now'))
                WHERE user_id = OLD.id AND revoked_at IS NULL;
            END
        """)
        if not schema.has_table("od_applications"):
            # Older demos can still create OD tables with prepare-od.
            return
        if "department_id" not in {column["name"] for column in schema.get_columns("od_applications")}:
            db.exec_driver_sql("""
                ALTER TABLE od_applications
                ADD COLUMN department_id UUID REFERENCES departments(id) ON DELETE RESTRICT
            """)
            db.exec_driver_sql("""
                UPDATE od_applications SET department_id = (
                    SELECT student.department_id FROM student_profiles AS student
                    WHERE student.id = od_applications.student_id
                )
            """)
        db.exec_driver_sql("""
            CREATE INDEX IF NOT EXISTS ix_od_applications_department_id ON od_applications(department_id)
        """)
        if "hod_assignment_id" not in {column["name"] for column in schema.get_columns("application_status_history")}:
            db.exec_driver_sql("""
                ALTER TABLE application_status_history
                ADD COLUMN hod_assignment_id UUID REFERENCES hod_assignments(id) ON DELETE RESTRICT
            """)
