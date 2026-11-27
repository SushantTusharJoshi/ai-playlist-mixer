"""PM-F4 summary cache and PM-N4 cost bound."""
from __future__ import annotations

import math
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agents.llm_agent import LLMAgent
from tests.conftest import host_headers
from tests.stubs import StubProvider


@pytest.fixture()
def stub(monkeypatch) -> StubProvider:
    provider = StubProvider()
    monkeypatch.setattr(main, "llm_agent", LLMAgent([provider]))
    return provider


@pytest.fixture()
def room(client: TestClient) -> str:
    code = client.post("/party/create", json={}).json()["code"]
    client.post(f"/party/{code}/join", json={"display_name": "Ann", "genre": "pop"})
    client.post(f"/party/{code}/join", json={"display_name": "Bo", "genre": "rock"})
    return code


def _generate(client, code):
    resp = client.post(f"/party/{code}/generate-queue", headers=host_headers(code))
    assert resp.status_code == 200
    return resp.json()


def test_unchanged_room_makes_zero_calls(client, room, stub, monkeypatch):
    monkeypatch.setattr(main, "SUMMARY_COOLDOWN", 0)  # so only the cache can skip the call
    _generate(client, room)
    assert stub.calls == 1
    for _ in range(5):
        _generate(client, room)
    assert stub.calls == 1


def test_reorder_makes_exactly_one_call(client, room, stub, monkeypatch):
    monkeypatch.setattr(main, "SUMMARY_COOLDOWN", 0)
    queue = _generate(client, room)["queue"]
    assert stub.calls == 1
    resp = client.post(f"/party/{room}/vote", json={"track_id": queue[0]["track_id"], "value": -1},
                       headers=host_headers(room))
    assert resp.status_code == 200
    reordered = _generate(client, room)["queue"]
    assert [q["track_id"] for q in reordered[:8]] != [q["track_id"] for q in queue[:8]]
    assert stub.calls == 2
    _generate(client, room)
    assert stub.calls == 2  # and cached again


def test_change_outside_the_prompt_makes_no_call(client, room, stub, monkeypatch):
    """The prompt shows the top 8 tracks; a vote that leaves them as they were costs nothing."""
    monkeypatch.setattr(main, "SUMMARY_COOLDOWN", 0)
    queue = _generate(client, room)["queue"]
    client.post(f"/party/{room}/vote", json={"track_id": queue[-1]["track_id"], "value": -1},
                headers=host_headers(room))
    again = _generate(client, room)["queue"]
    assert [(q["track_id"], q["score"]) for q in again[:8]] == [(q["track_id"], q["score"]) for q in queue[:8]]
    assert stub.calls == 1


def test_now_playing_and_new_guest_change_the_key(client, room, stub, monkeypatch):
    monkeypatch.setattr(main, "SUMMARY_COOLDOWN", 0)
    queue = _generate(client, room)["queue"]
    client.post(f"/party/{room}/now-playing", headers=host_headers(room),
                json={"track_id": queue[0]["track_id"], "name": queue[0]["name"], "artist": queue[0]["artist"]})
    _generate(client, room)
    assert stub.calls == 2
    client.post(f"/party/{room}/join", json={"display_name": "Cy", "genre": "jazz"})
    _generate(client, room)
    assert stub.calls == 3


def test_cooldown_still_applies_when_the_room_changes(client, room, stub):
    queue = _generate(client, room)["queue"]
    first = main.PARTIES[room].ai_summary
    client.post(f"/party/{room}/vote", json={"track_id": queue[-1]["track_id"], "value": 1},
                headers=host_headers(room))
    _generate(client, room)
    assert stub.calls == 1  # changed, but inside the 30 s cooldown
    assert main.PARTIES[room].ai_summary == first


def test_cost_bound_under_a_busy_host(client, room, stub, monkeypatch):
    """200 Generate clicks over 10 simulated minutes, with the room changing before each click.
    Bound: one call per party per cooldown window, so at most ceil(600 / 30) + 1 calls."""
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(time, "time", lambda: clock["t"])
    queue = _generate(client, room)["queue"]
    track = queue[0]["track_id"]
    value = 1
    for _ in range(200):
        clock["t"] += 3.0  # one click every 3 seconds
        client.post(f"/party/{room}/vote", json={"track_id": track, "value": value}, headers=host_headers(room))
        value = -value
        _generate(client, room)
    elapsed = 200 * 3.0
    assert stub.calls <= math.ceil(elapsed / main.SUMMARY_COOLDOWN) + 1
    assert stub.calls >= 2  # the summary still refreshes after the cooldown


def test_failed_provider_falls_through_to_the_next(client, room, monkeypatch):
    down, up = StubProvider(name="groq", fail=True), StubProvider(name="bedrock", reply="Backup DJ here.")
    monkeypatch.setattr(main, "llm_agent", LLMAgent([down, up]))
    assert _generate(client, room)["ai_summary"] == "Backup DJ here."
    assert (down.calls, up.calls) == (1, 1)
