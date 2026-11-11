"""Database engine, session factory and schema bootstrap."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import PlatformSettings


class Base(DeclarativeBase):
    pass


def build_engine(settings: PlatformSettings) -> Engine:
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    if settings.database_url.startswith("sqlite:///"):
        database = make_url(settings.database_url).database
        if database and database != ":memory:":
            Path(database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db(engine: Engine) -> None:
    from . import models  # noqa: F401 - register mappings

    Base.metadata.create_all(engine)


def verify_migrations(engine: Engine, api_dir: Path | None = None) -> None:
    """Fail fast when a production database is behind Alembic head."""

    api_dir = api_dir or Path(__file__).resolve().parents[1]
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        current = None
        if "alembic_version" in tables:
            current = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()

    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if current is None:
        raise RuntimeError(
            "database is not migrated: alembic_version is missing. "
            "Run `alembic upgrade head` before starting the API."
        )
    if current != head:
        raise RuntimeError(
            f"database migration mismatch: current={current} head={head}. "
            "Run `alembic upgrade head` before starting the API."
        )
