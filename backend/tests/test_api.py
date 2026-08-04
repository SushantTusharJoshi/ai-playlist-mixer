"""Smoke tests for API endpoints."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "v" in body


def test_genres(client: TestClient):
    resp = client.get("/genres")
    assert resp.status_code == 200
    genres = resp.json()["genres"]
    assert isinstance(genres, list)
    assert len(genres) > 0
    assert "pop" in genres


def test_create_party(client: TestClient):
    resp = client.post("/party/create", json={"host_id": "h1", "theme": "chill"})
    assert resp.status_code == 200
    body = resp.json()
    assert "code" in body
    assert len(body["code"]) == 6


def test_join_party(client: TestClient, party_code: str):
    resp = client.post(
        f"/party/{party_code}/join",
        json={"display_name": "Bob", "genre": "rock"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "user_id" in body
    assert body["user_id"].startswith("user-")
    assert len(body["members"]) == 1


def test_poll_party(client: TestClient, party_with_member: tuple[str, str]):
    code, _ = party_with_member
    resp = client.get(f"/party/{code}/poll")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == code
    assert len(body["members"]) == 1
    assert isinstance(body["queue"], list)


def test_vote(client: TestClient, party_with_member: tuple[str, str]):
    code, _ = party_with_member
    # Generate a queue first so there are tracks to vote on
    resp = client.post(f"/party/{code}/generate-queue")
    assert resp.status_code == 200
    queue = resp.json()["queue"]
    assert len(queue) > 0

    track_id = queue[0]["track_id"]
    resp = client.post(
        f"/party/{code}/vote",
        json={"track_id": track_id, "value": 1},
    )
    assert resp.status_code == 200
    assert "queue" in resp.json()


def test_party_not_found(client: TestClient):
    resp = client.get("/party/INVALID")
    assert resp.status_code == 404
