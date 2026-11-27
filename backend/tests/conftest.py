from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.data import PARTIES
from app.main import app


@pytest.fixture()
def room_file(tmp_path, monkeypatch):
    """Point room persistence at a temp file for this test."""
    from app import main
    from app.persistence import RoomStore
    path = tmp_path / "rooms.json"
    monkeypatch.setattr(main, "room_store", RoomStore(path, main.settings.room_idle_ttl_seconds))
    return path


@pytest.fixture()
def client(room_file):
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


def host_headers(code: str) -> dict[str, str]:
    """Headers the host page sends: the host key returned by /party/create."""
    return {"X-Host-Key": PARTIES[code].host_key}


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


@pytest.fixture(autouse=True)
def _reset_search_state():
    from app.services.search import reset_search_state
    reset_search_state()
    yield
    reset_search_state()
