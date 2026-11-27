"""PM-N4 cost bound: LLM summary calls over one simulated hour of a party.

Fake clock (time.time), fake provider that counts calls. Seven guest devices poll every
3 seconds and the host presses Generate on every tick (worst case: the host page itself
waits 30 s between presses). Generate is the only route that can call the model.
"""
from __future__ import annotations

import random
import time

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agents.llm_agent import LLMAgent
from tests.conftest import host_headers
from tests.stubs import StubProvider

HOUR = 3600
TICK = 3  # seconds between polls
DEVICES = 7
MAX_CALLS_PER_HOUR = HOUR // 30  # one call per 30-second cooldown window


@pytest.fixture()
def clock(monkeypatch) -> dict[str, float]:
    now = {"t": 1_000_000.0}
    monkeypatch.setattr(time, "time", lambda: now["t"])
    return now


@pytest.fixture()
def stub(monkeypatch) -> StubProvider:
    provider = StubProvider()
    monkeypatch.setattr(main, "llm_agent", LLMAgent([provider]))
    return provider


@pytest.fixture()
def party(client: TestClient):
    code = client.post("/party/create", json={}).json()["code"]
    genres = ["pop", "rock", "jazz", "hip hop", "edm", "latin", "r&b"]
    keys = []
    for i in range(DEVICES):
        resp = client.post(f"/party/{code}/join", json={"display_name": f"Guest {i}", "genre": genres[i % len(genres)]})
        assert resp.status_code == 200, resp.text
        keys.append(resp.json()["user_key"])
    return code, keys


def _run_hour(client, code, keys, clock, stub, change=None):
    """Play one hour in 3-second ticks. `change(tick, queue)` may alter the room before Generate."""
    start = clock["t"]
    polls = 0
    queue = []
    assert client.get(f"/party/{code}/poll").status_code == 200  # the route, once, over HTTP
    for tick in range(HOUR // TICK):
        clock["t"] = start + tick * TICK
        for _ in keys:
            # The poll handler itself; skipping HTTP encoding of the queue keeps the hour fast.
            assert main.poll(code)["code"] == code
            polls += 1
        if change and queue:
            change(tick, queue)
        resp = client.post(f"/party/{code}/generate-queue", headers=host_headers(code))
        assert resp.status_code == 200
        queue = resp.json()["queue"]
    assert polls == DEVICES * HOUR // TICK
    return stub.calls


def test_unchanged_room_costs_one_call_per_hour(client, party, clock, stub):
    code, keys = party
    calls = _run_hour(client, code, keys, clock, stub)
    print(f"\nPM-N4 unchanged room: {calls} LLM call(s) in one hour")
    assert calls == 1  # the first summary; every later Generate hits the cache


def test_realistic_party_stays_under_the_cooldown_bound(client, party, clock, stub):
    """A vote, an add or a song change every 2 to 5 minutes."""
    code, keys = party
    rng = random.Random(4)
    due = {0}
    t = 0
    while t < HOUR // TICK:
        t += rng.randint(40, 100)  # 40 to 100 ticks = 2 to 5 minutes
        due.add(t)
    events = 0

    def change(tick, queue):
        nonlocal events
        if tick not in due:
            return
        events += 1
        kind = rng.choice(["vote", "add", "song"])
        if kind == "vote":
            for _ in range(20):  # find a guest who has not voted this way on this track yet
                track = rng.choice(queue[:8])["track_id"]
                resp = client.post(f"/party/{code}/vote", json={"track_id": track, "value": rng.choice([1, -1])},
                                   headers={"X-User-Key": rng.choice(keys)})
                if resp.status_code == 200:
                    break
        elif kind == "add":
            resp = client.post(f"/party/{code}/add-track", headers={"X-User-Key": rng.choice(keys)},
                               json={"id": f"added-{tick}", "name": f"Request {tick}", "artist": "A Guest"})
            assert resp.status_code == 200
        else:
            item = rng.choice(queue[:8])
            resp = client.post(f"/party/{code}/now-playing", headers=host_headers(code),
                               json={"track_id": item["track_id"], "name": item["name"], "artist": item["artist"]})
            assert resp.status_code == 200

    calls = _run_hour(client, code, keys, clock, stub, change)
    print(f"\nPM-N4 realistic party: {calls} LLM call(s) in one hour for {events} room changes")
    assert calls <= events + 1  # no call without a change
    assert calls <= MAX_CALLS_PER_HOUR
    assert calls >= 2  # the summary does refresh when the room changes


def test_room_changing_every_tick_is_capped_by_the_cooldown(client, party, clock, stub):
    """Worst case: now playing changes before every Generate, so the key is new every 3 seconds."""
    code, keys = party

    def change(tick, queue):
        item = queue[tick % 8]
        resp = client.post(f"/party/{code}/now-playing", headers=host_headers(code),
                           json={"track_id": item["track_id"], "name": item["name"], "artist": item["artist"]})
        assert resp.status_code == 200

    calls = _run_hour(client, code, keys, clock, stub, change)
    print(f"\nPM-N4 room changing every 3 s: {calls} LLM call(s) in one hour")
    assert calls <= MAX_CALLS_PER_HOUR
