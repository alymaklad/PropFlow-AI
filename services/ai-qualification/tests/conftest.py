import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

ROOT = Path(__file__).resolve().parents[3]
TEST_API_KEY = "test-key"


def load_dataset() -> list[dict]:
    path = ROOT / "sample-data" / "synthetic-leads.json"
    return json.loads(path.read_text(encoding="utf-8"))["records"]


@pytest.fixture
def client():
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=None, api_key=TEST_API_KEY, llm_provider="fake"
    )
    yield TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    app.dependency_overrides.clear()
