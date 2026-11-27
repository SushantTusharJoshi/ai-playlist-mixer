"""Regression tests for the findings in SECURITY.md."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import main
from app.data import PARTIES
from app.services import search as search_mod
from tests.conftest import host_headers


def _join(client: TestClient, code: str, name: str = "Guest", genre: str = "pop") -> dict:
    resp = client.post(f"/party/{code}/join", json={"display_name": name, "genre": genre})
    assert resp.status_code == 200
    return resp.json()


def _queue(client: TestClient, code: str) -> list[dict]:
    resp = client.post(f"/party/{code}/generate-queue", headers=host_headers(code))
    assert resp.status_code == 200
    return resp.json()["queue"]


# SEC-1: Spotify tokens are not readable with the party code alone

def test_get_party_hides_tokens_and_keys(client: TestClient, party_code: str):
    PARTIES[party_code].spotify_token = "ACCESS"
    PARTIES[party_code].spotify_refresh = "REFRESH"
    body = client.get(f"/party/{party_code}").json()
    for field in ("spotify_token", "spotify_refresh", "host_key", "member_keys", "vote_choices"):
        assert field not in body
    assert "REFRESH" not in str(body) and "ACCESS" not in str(body)


def test_spotify_token_needs_host_key(client: TestClient, party_code: str):
    PARTIES[party_code].spotify_token = "ACCESS"
    assert client.get(f"/party/{party_code}/spotify-token").status_code == 403
    assert client.get(f"/party/{party_code}/spotify-token", headers={"X-Host-Key": "wrong"}).status_code == 403
    ok = client.get(f"/party/{party_code}/spotify-token", headers=host_headers(party_code))
    assert ok.json() == {"token": "ACCESS"}
    assert client.post(f"/party/{party_code}/refresh-token").status_code == 403


def test_create_returns_host_key_once(client: TestClient):
    created = client.post("/party/create", json={}).json()
    assert len(created["host_key"]) >= 24
    assert "host_key" not in client.get(f"/party/{created['code']}").json()


# SEC-2: OAuth state is a single-use server nonce bound to the party

def test_login_url_needs_host_key(client: TestClient, party_code: str):
    assert client.post(f"/party/{party_code}/spotify/login-url").status_code == 403
    assert client.get(f"/auth/spotify/login?party_code={party_code}").status_code in (404, 405)


def test_callback_rejects_forged_state(client: TestClient, party_code: str, monkeypatch):
    async def fake_exchange(code):
        return {"access_token": "ATTACKER", "refresh_token": "R"}
    monkeypatch.setattr(main, "exchange_code_for_token", fake_exchange)
    resp = client.get(f"/auth/spotify/callback?code=x&state={party_code}:abc", follow_redirects=False)
    assert resp.status_code == 400
    assert PARTIES[party_code].spotify_token == ""


def test_callback_accepts_issued_state_once(client: TestClient, party_code: str, monkeypatch):
    async def fake_exchange(code):
        return {"access_token": "HOST", "refresh_token": "R"}
    monkeypatch.setattr(main, "exchange_code_for_token", fake_exchange)
    url = client.post(f"/party/{party_code}/spotify/login-url", headers=host_headers(party_code)).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    assert party_code not in state
    first = client.get(f"/auth/spotify/callback?code=x&state={state}", follow_redirects=False)
    assert first.status_code == 307
    assert first.headers["location"].endswith(f"/host/{party_code}?spotify=connected")
    assert PARTIES[party_code].spotify_token == "HOST"
    replay = client.get(f"/auth/spotify/callback?code=x&state={state}", follow_redirects=False)
    assert replay.status_code == 400


# SEC-3: host-only actions need the host key

@pytest.mark.parametrize("path, body", [
    ("generate-queue", None),
    ("now-playing", {"track_id": "p01", "name": "x", "artist": "y"}),
    ("stop-playing", None),
])
def test_host_only_endpoints(client: TestClient, party_with_member, path, body):
    code, _ = party_with_member
    assert client.post(f"/party/{code}/{path}", json=body).status_code == 403
    assert client.post(f"/party/{code}/{path}", json=body, headers=host_headers(code)).status_code == 200


# SEC-4: one voter moves a track by at most one vote, and other tracks do not drift

def test_vote_needs_a_key(client: TestClient, party_with_member):
    code, _ = party_with_member
    track = _queue(client, code)[0]["track_id"]
    assert client.post(f"/party/{code}/vote", json={"track_id": track, "value": 1}).status_code == 401
    spoof = {"track_id": track, "value": 1, "voted_by": "anyone"}
    assert client.post(f"/party/{code}/vote", json=spoof).status_code == 401


def test_repeat_votes_are_rejected_and_switching_moves_by_two(client: TestClient, party_code: str):
    guest = _join(client, party_code)
    hdr = {"X-User-Key": guest["user_key"]}
    track = _queue(client, party_code)[0]["track_id"]
    assert client.post(f"/party/{party_code}/vote", json={"track_id": track, "value": 1}, headers=hdr).status_code == 200
    assert client.post(f"/party/{party_code}/vote", json={"track_id": track, "value": 1}, headers=hdr).status_code == 400
    switched = client.post(f"/party/{party_code}/vote", json={"track_id": track, "value": -1}, headers=hdr)
    assert switched.status_code == 200
    item = next(q for q in switched.json()["queue"] if q["track_id"] == track)
    assert item["votes"] == -1


def test_downvote_spam_cannot_lift_a_track(client: TestClient, party_code: str):
    """Before the fix, 60 downvotes moved the last track to position 0."""
    _join(client, party_code, "A", "pop")
    _join(client, party_code, "B", "rock")
    queue = _queue(client, party_code)
    lowest = min(queue, key=lambda q: q["score"])
    last = lowest["track_id"]
    others_before = {q["track_id"]: q["score"] for q in queue if q["track_id"] != last}
    for _ in range(60):
        client.post(f"/party/{party_code}/vote", json={"track_id": last, "value": -1}, headers=host_headers(party_code))
    after = client.get(f"/party/{party_code}/poll").json()["queue"]
    assert after[-1]["track_id"] == last
    mine = after[-1]
    assert mine["votes"] == -1  # 59 of the 60 were duplicates
    assert mine["score"] == round(lowest["score"] - 0.04, 4)
    assert {q["track_id"]: q["score"] for q in after if q["track_id"] != last} == others_before


def test_vote_on_unknown_track_is_rejected(client: TestClient, party_code: str):
    guest = _join(client, party_code)
    _queue(client, party_code)
    resp = client.post(f"/party/{party_code}/vote", json={"track_id": "nope", "value": 1},
                       headers={"X-User-Key": guest["user_key"]})
    assert resp.status_code == 404


# SEC-5: guest text is bounded and the name on an addition comes from the server

def test_display_name_is_capped(client: TestClient, party_code: str):
    resp = client.post(f"/party/{party_code}/join", json={"display_name": "x" * 41, "genre": "pop"})
    assert resp.status_code == 422


def test_added_by_cannot_be_spoofed(client: TestClient, party_code: str):
    guest = _join(client, party_code, "Mallory")
    track = {"id": "sp-1", "name": "Song", "artist": "Artist"}
    assert client.post(f"/party/{party_code}/add-track?added_by=Host", json=track).status_code == 401
    resp = client.post(f"/party/{party_code}/add-track?added_by=Host", json=track,
                       headers={"X-User-Key": guest["user_key"]})
    assert resp.json()["added"] is True
    reasons = PARTIES[party_code].queue[-1].reasons
    assert reasons == ["added by Mallory"]


def test_queue_is_capped(client: TestClient, party_code: str, monkeypatch):
    monkeypatch.setattr(main.settings, "max_queue", 2)
    for i in range(2):
        assert client.post(f"/party/{party_code}/add-track", json={"id": f"t{i}", "name": "n", "artist": "a"},
                           headers=host_headers(party_code)).json()["added"]
    resp = client.post(f"/party/{party_code}/add-track", json={"id": "t9", "name": "n", "artist": "a"},
                       headers=host_headers(party_code))
    assert resp.status_code == 400


def test_party_count_is_capped(client: TestClient, monkeypatch):
    monkeypatch.setattr(main.settings, "max_parties", 1)
    assert client.post("/party/create", json={}).status_code == 200
    assert client.post("/party/create", json={}).status_code == 503


# SEC-6: search fan-out is bounded

def test_search_limit_is_bounded(client: TestClient):
    assert client.post("/search", json={"query": "pop", "limit": 1000}).status_code == 422
    assert client.post("/search", json={"query": "x" * 101}).status_code == 422


def test_search_cache_and_youtube_budget(client: TestClient, monkeypatch):
    calls = {"yt": 0}

    async def fake_yt(q, limit=5):
        calls["yt"] += 1
        return [{"id": f"yt-{q}", "name": q, "artist": "c"}]

    monkeypatch.setattr(search_mod, "spotify_is_configured", lambda: False)
    monkeypatch.setattr(search_mod, "youtube_is_configured", lambda: True)
    monkeypatch.setattr(search_mod, "youtube_search", fake_yt)
    monkeypatch.setattr(search_mod.settings, "youtube_calls_per_minute", 2)

    for _ in range(5):
        client.post("/search", json={"query": "same", "limit": 10})
    assert calls["yt"] == 1  # cached after the first call

    client.post("/search", json={"query": "two", "limit": 10})
    third = client.post("/search", json={"query": "three", "limit": 10}).json()
    assert calls["yt"] == 2  # budget of 2 per minute reached
    assert third["source"] == "local"
