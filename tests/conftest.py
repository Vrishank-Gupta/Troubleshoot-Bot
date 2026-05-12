"""Pytest configuration and shared fixtures."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend to path and set SQLite env before any app imports
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.environ["DATABASE_URL"] = "sqlite:///./test_chatbot.db"
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.chdir(Path(__file__).parent.parent / "backend")

from app.database import Base, get_db

TEST_DB_URL = "sqlite:///./test_chatbot.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def create_test_tables():
    """Create all ORM tables in SQLite for the test session."""
    # Patch pgvector import so it doesn't fail
    import unittest.mock as mock_module
    pgvector_mock = mock_module.MagicMock()
    pgvector_mock.sqlalchemy.Vector = lambda n: None
    with mock_module.patch.dict("sys.modules", {
        "pgvector": pgvector_mock,
        "pgvector.sqlalchemy": pgvector_mock.sqlalchemy,
    }):
        # Override the engine in app.database to use SQLite
        import app.database as db_mod
        db_mod.engine = test_engine
        db_mod.SessionLocal = TestingSessionLocal
        # Always recreate schema fresh — prevents stale column errors after model changes
        Base.metadata.drop_all(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    db_path = Path("./test_chatbot.db")
    if db_path.exists():
        try:
            db_path.unlink()
        except Exception:
            pass


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db):
    from app.main import app

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_sop_json():
    seeds_dir = Path(__file__).parent.parent / "data" / "seeds"
    return json.loads((seeds_dir / "wifi_router_no_internet.json").read_text(encoding="utf-8"))


@pytest.fixture
def mock_llm():
    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_embed():
    with patch("app.services.embedding_service.embed_text", new_callable=AsyncMock) as mock:
        mock.return_value = [0.1] * 1536
        with patch("app.services.embedding_service.embed_batch", new_callable=AsyncMock) as batch:
            batch.return_value = [[0.1] * 1536]
            yield mock, batch
