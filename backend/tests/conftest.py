from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.data import PARTIES
from app.main import app


@pytest.fixture()
def client():
    """FastAPI test client that clears party state between tests."""
    PARTIES.clear()
    with TestClient(app) as c:
        yield c
    PARTIES.clear()


@pytest.fixture()
def party_code(client: TestClient) -> str:
    """Create a party and return its code."""
    resp = client.post("/party/create", json={"host_id": "test-host", "theme": "smoke test"})
    assert resp.status_code == 200
    return resp.json()["code"]


@pytest.fixture()
def party_with_member(client: TestClient, party_code: str) -> tuple[str, str]:
    """Create a party with one member. Returns (party_code, user_id)."""
    resp = client.post(
        f"/party/{party_code}/join",
        json={"display_name": "Alice", "genre": "pop"},
    )
    assert resp.status_code == 200
    user_id = resp.json()["user_id"]
    return party_code, user_id
