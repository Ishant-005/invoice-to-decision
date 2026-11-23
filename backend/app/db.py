"""Database connection (SQLite through SQLModel)."""

import threading
from collections.abc import Iterator
from decimal import Decimal

from sqlalchemy import Engine, String, TypeDecorator
from sqlmodel import Session, SQLModel, create_engine

from app import config


class DecimalText(TypeDecorator):
    """Store a Decimal as text, e.g. '100000.00'.

    SQLite has no exact decimal type: its NUMERIC columns go through floating point, which
    can turn 0.10 into 0.1000000000000000055. Money must be exact, so we keep the digits as
    text in the database and turn them back into Decimal when reading.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


def make_engine(url: str = config.DATABASE_URL) -> Engine:
    if url.startswith("sqlite:///"):
        config.VAR_DIR.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI serves requests on several threads.
    return create_engine(url, connect_args={"check_same_thread": False})


engine = make_engine()

# One lock for everything that reads or changes the shared books (PO balances, invoice
# history): the decision stages of a run, a person resolving a review, and a demo reset.
# Holding it means two invoices can never both be checked against the same PO balance at
# the same moment and both be approved. The slow AI call is made outside the lock.
# (An RLock may be taken again by the thread that already holds it.)
STATE_LOCK = threading.RLock()


def create_tables(db_engine: Engine = engine) -> None:
    from app import models  # noqa: F401  (importing registers the tables)

    SQLModel.metadata.create_all(db_engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with Session(engine) as session:
        yield session
