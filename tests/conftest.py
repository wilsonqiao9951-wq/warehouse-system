import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.database import get_db
from app.models import Organization
from app.main import app


TEST_DB_URL = "sqlite://"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        db.add(Organization(id=1, name="Test Organization", slug="test"))
        db.commit()
    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_local = TestingSessionLocal

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    del app.state.testing_session_local
    Base.metadata.drop_all(bind=engine)
