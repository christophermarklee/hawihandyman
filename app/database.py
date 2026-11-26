"""Engine/session setup.

SQLite specifics:
- All transactions are opened with BEGIN IMMEDIATE so the double-booking
  check in POST /api/book holds a write lock for its duration (PRD 8).
- WAL mode is intentionally not used: the production database lives on
  EFS/NFS where WAL's shared-memory file is unsafe. A busy timeout plus a
  single-writer deployment keeps the default rollback journal safe.
"""

from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from . import config
from .models import AppSettings, Service

_engine = None


def _configure(engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record):
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA busy_timeout = 5000")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def get_engine():
    global _engine
    if _engine is None:
        config.database_path().parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            config.database_url(), connect_args={"check_same_thread": False}
        )
        _configure(_engine)
    return _engine


def reset_engine() -> None:
    """Used by tests to point at a fresh database."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.get(AppSettings, 1) is None:
            session.add(AppSettings(id=1))
        if session.exec(select(Service)).first() is None:
            session.add_all(
                [
                    Service(name="1-Hour Small Repair", duration_minutes=60, rate=85.0),
                    Service(
                        name="Half-Day Project (4 hrs)",
                        duration_minutes=240,
                        rate=320.0,
                    ),
                    Service(
                        name="Full-Day Project (8 hrs)",
                        duration_minutes=480,
                        rate=600.0,
                    ),
                ]
            )
        session.commit()


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_settings(session: Session) -> AppSettings:
    settings = session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings
