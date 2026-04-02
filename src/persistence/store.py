"""Database engine/session setup for persistence modules."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.persistence.models import Base


def build_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine suitable for sqlite or Postgres."""
    kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


@dataclass(slots=True)
class DatabaseStore:
    """Wrapper around SQLAlchemy engine + session factory."""

    database_url: str
    engine: Engine = field(init=False, repr=False)
    session_factory: sessionmaker[Session] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.engine = build_engine(self.database_url)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def create_schema(self) -> None:
        """Create all known tables if they do not already exist."""
        Base.metadata.create_all(self.engine)

    def ping(self) -> bool:
        """Return True when the DB connection is healthy."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a transactional DB session with commit/rollback behavior."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
