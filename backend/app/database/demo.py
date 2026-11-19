"""SQLite transaction adapter for the isolated, single-machine demo."""

from pathlib import Path

from sqlalchemy import create_engine, event
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
