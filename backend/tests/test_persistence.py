"""Room state persistence: atomic writes, one writer, idle expiry, restart recovery."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app import main, persistence
from app.data import PARTIES
from app.models.schemas import JoinRequest, PartySession, VoteRequest
from app.persistence import RoomStore
from tests.conftest import host_headers

BACKEND = Path(__file__).resolve().parents[1]


def _room(code: str = "ABC123", **kw) -> PartySession:
    return PartySession(code=code, host_id="h", host_key="k", **kw)


def _saved_codes(path: Path) -> set[str]:
    return set(json.loads(path.read_text())["parties"])


# ── atomic writes ──────────────────────────────────

def test_save_and_load_round_trip(tmp_path):
    store = RoomStore(tmp_path / "rooms.json", idle_ttl_seconds=3600)
    parties = {"ABC123": _room(theme="disco")}
    assert store.save(parties)
    loaded = store.load()
    assert loaded["ABC123"].theme == "disco"
    assert loaded["ABC123"].host_key == "k"


def test_failed_replace_keeps_previous_file_and_no_temp_files(tmp_path, monkeypatch):
    path = tmp_path / "rooms.json"
    store = RoomStore(path, idle_ttl_seconds=3600)
    store.save({"OLD111": _room("OLD111")})
    before = path.read_text()

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(persistence.os, "replace", boom)

    assert store.save({"NEW222": _room("NEW222")}) is False  # the app keeps running
    assert path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["rooms.json"]


def test_crash_during_write_leaves_old_file_readable(tmp_path, monkeypatch):
    path = tmp_path / "rooms.json"
    store = RoomStore(path, idle_ttl_seconds=3600)
    store.save({"OLD111": _room("OLD111")})

    real_fsync = os.fsync

    def die_after_partial_write(fd):
        real_fsync(fd)
        raise OSError("power cut")
    monkeypatch.setattr(persistence.os, "fsync", die_after_partial_write)

    store.save({"NEW222": _room("NEW222")})
    assert set(store.load()) == {"OLD111"}
    assert not any(p.name.endswith(".tmp") for p in tmp_path.iterdir())


def test_tokens_are_not_written(tmp_path):
    path = tmp_path / "rooms.json"
    RoomStore(path, 3600).save({"ABC123": _room(spotify_token="ACCESS", spotify_refresh="REFRESH")})
    text = path.read_text()
    assert "ACCESS" not in text and "REFRESH" not in text


def test_corrupt_file_is_set_aside(tmp_path):
    path = tmp_path / "rooms.json"
    path.write_text("{not json")
    assert RoomStore(path, 3600).load() == {}
    assert (tmp_path / "rooms.json.corrupt").exists()


def test_one_bad_party_does_not_lose_the_rest(tmp_path):
    path = tmp_path / "rooms.json"
    good = _room("GOOD11").model_dump(mode="json")
    path.write_text(json.dumps({"version": 1, "parties": {"GOOD11": good, "BAD222": {"code": 5}}}))
    assert set(RoomStore(path, 3600).load()) == {"GOOD11"}


def test_empty_path_disables_persistence(tmp_path):
    store = RoomStore(None, 3600)
    assert store.save({"ABC123": _room()}) is False
    assert store.load() == {}


# ── one writer at a time ───────────────────────────

def test_writes_never_overlap(tmp_path, monkeypatch):
    store = RoomStore(tmp_path / "rooms.json", idle_ttl_seconds=3600)
    parties = {f"P{i:05d}": _room(f"P{i:05d}") for i in range(20)}
    active, peak = 0, 0
    guard = threading.Lock()
    real_replace = os.replace

    def tracking_replace(src, dst):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.002)
        real_replace(src, dst)
        with guard:
            active -= 1
    monkeypatch.setattr(persistence.os, "replace", tracking_replace)

    threads = [threading.Thread(target=store.save, args=(parties,)) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
    assert store.saves == 16
    assert _saved_codes(tmp_path / "rooms.json") == set(parties)


def test_concurrent_endpoint_calls_keep_counts_and_file_consistent(client: TestClient, room_file):
    """20 joins and 7 x 20 votes from parallel threads: no lost update, cap holds, file matches memory."""
    code = client.post("/party/create", json={}).json()["code"]
    key = PARTIES[code].host_key

    joined, errors = [], []

    def do_join(i):
        try:
            joined.append(main.join(code=code, req=JoinRequest(display_name=f"G{i}", genre="pop")))
        except Exception as e:  # the 8th+ join is rejected with HTTP 400
            errors.append(e)
    threads = [threading.Thread(target=do_join, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(PARTIES[code].members) == main.MAX_DEVICES == len(joined)

    queue = client.post(f"/party/{code}/generate-queue", headers={"X-Host-Key": key}).json()["queue"]
    tracks = [q["track_id"] for q in queue]

    def guest_votes(user_key):
        for tid in tracks:
            main.vote(code=code, req=VoteRequest(track_id=tid, value=1), x_host_key=None, x_user_key=user_key)
    keys = [j["user_key"] for j in joined]
    threads = [threading.Thread(target=guest_votes, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(PARTIES[code].votes[t] == len(keys) for t in tracks)
    saved = json.loads(room_file.read_text())["parties"][code]
    assert saved["votes"] == PARTIES[code].votes
    assert [q["track"]["id"] for q in saved["queue"]] == [q.track.id for q in PARTIES[code].queue]


# ── idle expiry ────────────────────────────────────

def test_idle_parties_expire_on_load_and_save(tmp_path):
    path = tmp_path / "rooms.json"
    store = RoomStore(path, idle_ttl_seconds=60)
    now = time.time()
    parties = {"FRESH1": _room("FRESH1", last_active_at=now), "STALE1": _room("STALE1", last_active_at=now - 61)}
    store.save(parties)
    assert set(parties) == {"FRESH1"}  # dropped from memory too
    assert _saved_codes(path) == {"FRESH1"}
    assert set(store.load(now=now + 120)) == set()  # both idle by then


def test_polling_keeps_a_party_alive(client: TestClient):
    code = client.post("/party/create", json={}).json()["code"]
    PARTIES[code].last_active_at = time.time() - 10_000
    client.get(f"/party/{code}/poll")
    assert time.time() - PARTIES[code].last_active_at < 5


def test_mutations_save_the_file(client: TestClient, room_file):
    code = client.post("/party/create", json={}).json()["code"]
    assert code in _saved_codes(room_file)
    client.post(f"/party/{code}/join", json={"display_name": "Ann", "genre": "jazz"})
    saved = json.loads(room_file.read_text())["parties"][code]
    assert [m["display_name"] for m in saved["members"]] == ["Ann"]


# ── restart recovery (PM-F10) ──────────────────────

FRESH_PROCESS = """
import json
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
    print(json.dumps(c.get("/party/%s/poll").json()))
"""


def test_fresh_process_restores_the_queue(client: TestClient, room_file):
    """State saved by this app instance is restored by a brand-new Python process."""
    code = client.post("/party/create", json={}).json()["code"]
    hdr = host_headers(code)
    guest = client.post(f"/party/{code}/join", json={"display_name": "Ann", "genre": "rock"}).json()
    client.post(f"/party/{code}/join", json={"display_name": "Bo", "genre": "latin"})
    queue = client.post(f"/party/{code}/generate-queue", headers=hdr).json()["queue"]
    client.post(f"/party/{code}/vote", json={"track_id": queue[3]["track_id"], "value": 1},
                headers={"X-User-Key": guest["user_key"]})
    client.post(f"/party/{code}/add-track", json={"id": "yt-abc", "name": "Live set", "artist": "DJ"}, headers=hdr)
    client.post(f"/party/{code}/now-playing", headers=hdr,
                json={"track_id": queue[0]["track_id"], "name": queue[0]["name"], "artist": queue[0]["artist"]})
    before = client.get(f"/party/{code}/poll").json()

    env = {**os.environ, "ROOM_STATE_PATH": str(room_file), "GROQ_API_KEY": ""}
    out = subprocess.run([sys.executable, "-c", FRESH_PROCESS % code], cwd=BACKEND, env=env,
                         capture_output=True, text=True, timeout=60, check=True)
    after = json.loads(out.stdout.strip().splitlines()[-1])

    assert after["queue"] == before["queue"]  # same tracks, order, scores and votes
    assert after["members"] == before["members"]
    assert after["now_playing"]["track_id"] == before["now_playing"]["track_id"]
    assert after["has_spotify"] is False  # tokens are not persisted


def test_restored_party_still_accepts_its_keys(client: TestClient, room_file):
    code = client.post("/party/create", json={}).json()["code"]
    guest = client.post(f"/party/{code}/join", json={"display_name": "Ann", "genre": "pop"}).json()
    key = PARTIES[code].host_key

    PARTIES.clear()  # simulate the restart inside this process
    with TestClient(main.app) as fresh:
        queue = fresh.post(f"/party/{code}/generate-queue", headers={"X-Host-Key": key}).json()["queue"]
        resp = fresh.post(f"/party/{code}/vote", json={"track_id": queue[0]["track_id"], "value": 1},
                          headers={"X-User-Key": guest["user_key"]})
        assert resp.status_code == 200
