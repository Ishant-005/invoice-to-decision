import pytest
from sqlmodel import Session

from app.db import create_tables, make_engine


@pytest.fixture
def session(tmp_path):
    """A session on a brand-new, empty database in a temporary folder."""
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    create_tables(engine)
    with Session(engine) as db_session:
        yield db_session
