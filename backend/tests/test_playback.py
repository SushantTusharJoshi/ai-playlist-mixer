"""Player transitions: play, next, previous, pause/seek, track end races, token refresh."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import main, playback
from app.data import PARTIES
from app.models.schemas import Track
from app.persistence import RoomStore
from app.services import resolve
from tests.conftest import host_headers

YT = ["dQw4w9WgXcQ", "jNQXAC9IVRw", "9bZkp7q19f0"]


@pytest.fixture()
def room(client: TestClient, party_with_member) -> str:
    """Generated catalog queue (no playable source) plus three YouTube tracks at the end."""
    code, _ = party_with_member
    assert client.post(f"/party/{code}/generate-queue", headers=host_headers(code)).status_code == 200
    for i, vid in enumerate(YT):
        client.post(f"/party/{code}/add-track", headers=host_headers(code),
                    json={"id": f"yt-{vid}", "name": f"Video {i}", "artist": "YT"})
    resolve.reset_resolve_cache()
    return code


def _post(client, code, path, body=None, headers=None):
    return client.post(f"/party/{code}/{path}", json=body or {}, headers=headers if headers is not None else host_headers(code))


def _np(client, code) -> dict:
    return client.get(f"/party/{code}/poll").json()["now_playing"]


def test_play_youtube_track_sets_source_and_bumps_seq(client, room):
    r = _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    assert r.status_code == 200
    np = r.json()["now_playing"]
    assert np["source"] == "youtube" and np["youtube_id"] == YT[0]
    assert np["seq"] == 1 and np["is_playing"] is True and np["position_ms"] == 0
    assert _np(client, room) == np  # poll shows the same state


def test_catalog_track_without_a_source_is_refused(client, room):
    catalog = PARTIES[room].queue[0].track.id
    r = _post(client, room, "play", {"track_id": catalog})
    assert r.status_code == 409
    assert _np(client, room)["seq"] == 0


def test_search_link_fallback_is_not_a_video():
    assert playback.youtube_id_of(Track(id="yt-search-daft%20punk", name="x", artist="y")) is None
    assert playback.youtube_id_of(Track(id=f"yt-{YT[0]}", name="x", artist="y")) == YT[0]
    assert playback.youtube_id_of(Track(id="sp-1", name="x", artist="y", youtube_id=YT[1])) == YT[1]


def test_spotify_track_plays_only_when_the_host_is_connected():
    t = Track(id="sp-1", name="x", artist="y", uri="spotify:track:1")
    assert playback.source_of(t, has_spotify=False) is None
    assert playback.source_of(t, has_spotify=True) == "spotify"


def test_next_skips_tracks_that_cannot_play_and_records_history(client, room):
    last_catalog = PARTIES[room].queue[-4].track.id
    PARTIES[room].now_playing.track_id = last_catalog  # pretend the last catalog track was playing
    r = _post(client, room, "next", {"expected_seq": 0})
    assert r.json()["changed"] is True
    assert r.json()["now_playing"]["track_id"] == f"yt-{YT[0]}"
    r = _post(client, room, "next", {"expected_seq": 1})
    assert r.json()["now_playing"]["track_id"] == f"yt-{YT[1]}"
    assert PARTIES[room].history[-1] == f"yt-{YT[0]}"
    assert r.json()["prev_track_id"] == f"yt-{YT[0]}"
    poll = client.get(f"/party/{room}/poll").json()
    assert poll["up_next_track_id"] == f"yt-{YT[2]}" and poll["prev_track_id"] == f"yt-{YT[0]}"


def test_track_end_and_tap_race_skip_only_once(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    seq = _np(client, room)["seq"]
    first = _post(client, room, "next", {"expected_seq": seq})   # the ended event
    second = _post(client, room, "next", {"expected_seq": seq})  # the tap, sent before the reply arrived
    assert first.json()["changed"] is True
    assert second.json()["changed"] is False
    assert _np(client, room)["track_id"] == f"yt-{YT[1]}"
    assert _np(client, room)["seq"] == seq + 1


def test_end_of_queue_stops_and_repeat_starts_over(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[2]}"})
    PARTIES[room].history[:] = [f"yt-{YT[0]}", f"yt-{YT[1]}"]
    ended = _post(client, room, "next", {"expected_seq": 1}).json()["now_playing"]
    assert ended["ended"] is True and ended["is_playing"] is False and ended["track_id"] == ""
    _post(client, room, "play", {"track_id": f"yt-{YT[2]}"})
    seq = _np(client, room)["seq"]
    PARTIES[room].history[:] = [f"yt-{YT[0]}", f"yt-{YT[1]}"]
    wrapped = _post(client, room, "next", {"expected_seq": seq, "repeat": True}).json()["now_playing"]
    assert wrapped["track_id"] == f"yt-{YT[0]}"  # first playable track in the queue
    assert PARTIES[room].history == [f"yt-{YT[2]}"]


def test_previous_goes_back_and_next_returns(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    _post(client, room, "next", {"expected_seq": 1})
    assert _np(client, room)["track_id"] == f"yt-{YT[1]}"
    back = _post(client, room, "prev", {"expected_seq": 2}).json()
    assert back["changed"] is True and back["now_playing"]["track_id"] == f"yt-{YT[0]}"
    assert PARTIES[room].history == []
    fwd = _post(client, room, "next", {"expected_seq": 3}).json()
    assert fwd["now_playing"]["track_id"] == f"yt-{YT[1]}"


def test_previous_with_no_history_restarts_the_track(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[1]}"})
    _post(client, room, "playback", {"seq": 1, "is_playing": True, "position_ms": 90_000, "duration_ms": 200_000})
    r = _post(client, room, "prev", {"expected_seq": 1}).json()
    assert r["changed"] is True
    np = r["now_playing"]
    assert np["track_id"] == f"yt-{YT[1]}" and np["seq"] == 2 and np["position_ms"] == 0


def test_previous_skips_tracks_removed_or_unplayable(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[2]}"})
    PARTIES[room].history[:] = [f"yt-{YT[0]}", "gone-from-queue", PARTIES[room].queue[0].track.id]
    r = _post(client, room, "prev", {"expected_seq": 1}).json()
    assert r["now_playing"]["track_id"] == f"yt-{YT[0]}"


def test_pause_resume_and_seek_keep_the_track(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    r = _post(client, room, "playback", {"seq": 1, "is_playing": False, "position_ms": 42_000, "duration_ms": 213_000})
    np = r.json()["now_playing"]
    assert r.json()["changed"] is True
    assert np["is_playing"] is False and np["position_ms"] == 42_000 and np["duration_ms"] == 213_000
    assert np["seq"] == 1  # same track, so clients do not reload
    assert _np(client, room)["is_playing"] is False  # a poll no longer flips it back to playing


def test_playback_report_for_an_old_track_is_ignored(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    _post(client, room, "next", {"expected_seq": 1})
    r = _post(client, room, "playback", {"seq": 1, "is_playing": False, "position_ms": 5})
    assert r.json()["changed"] is False
    assert _np(client, room)["is_playing"] is True


def test_queue_next_track_is_played_next(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    client.post(f"/party/{room}/queue-next", headers=host_headers(room),
                json={"id": "yt-aaaaaaaaaaa", "name": "Jumped in", "artist": "Guest"})
    r = _post(client, room, "next", {"expected_seq": 1}).json()
    assert r["now_playing"]["track_id"] == "yt-aaaaaaaaaaa"


def test_shuffle_picks_an_unplayed_track(client, room):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    r = _post(client, room, "next", {"expected_seq": 1, "shuffle": True}).json()
    assert r["now_playing"]["track_id"] in {f"yt-{YT[1]}", f"yt-{YT[2]}"}


@pytest.mark.parametrize("path, body", [
    ("play", {"track_id": f"yt-{YT[0]}"}),
    ("next", {}),
    ("prev", {}),
    ("playback", {"seq": 0, "is_playing": False}),
])
def test_player_controls_are_host_only(client, room, path, body):
    assert _post(client, room, path, body, headers={}).status_code == 403
    guest_key = next(iter(PARTIES[room].member_keys))
    assert _post(client, room, path, body, headers={"X-User-Key": guest_key}).status_code == 403


def test_catalog_track_is_matched_to_youtube(client, room, monkeypatch):
    calls = []

    async def fake_resolve(track_id, name, artist, has_spotify):
        calls.append(track_id)
        return {"youtube_id": "bbbbbbbbbbb", "album_art": "https://i.ytimg.com/x.jpg"}
    monkeypatch.setattr(main, "resolve_track", fake_resolve)
    monkeypatch.setattr(main, "can_resolve", lambda has_spotify: True)
    first = PARTIES[room].queue[0].track.id
    np = _post(client, room, "play", {"track_id": first}).json()["now_playing"]
    assert np["source"] == "youtube" and np["youtube_id"] == "bbbbbbbbbbb"
    assert np["album_art"] == "https://i.ytimg.com/x.jpg"
    poll_item = client.get(f"/party/{room}/poll").json()["queue"][0]
    assert poll_item["youtube_id"] == "bbbbbbbbbbb"  # stored, so the next play needs no search
    _post(client, room, "play", {"track_id": first})
    assert calls == [first]
    from app.data import TRACK_CATALOG
    assert TRACK_CATALOG[first].youtube_id is None  # other parties share catalog tracks: no leak


def test_catalog_track_is_matched_to_spotify_for_a_connected_host(client, room, monkeypatch):
    async def fake_resolve(track_id, name, artist, has_spotify):
        assert has_spotify is True
        return {"uri": "spotify:track:abc"}
    monkeypatch.setattr(main, "resolve_track", fake_resolve)
    monkeypatch.setattr(main, "can_resolve", lambda has_spotify: True)
    PARTIES[room].spotify_token = "ACCESS"
    np = _post(client, room, "play", {"track_id": PARTIES[room].queue[0].track.id}).json()["now_playing"]
    assert np["source"] == "spotify" and np["uri"] == "spotify:track:abc"


def test_next_bounds_upstream_searches(client, room, monkeypatch):
    calls = []

    async def miss(track_id, name, artist, has_spotify):
        calls.append(track_id)
        return None
    monkeypatch.setattr(main, "resolve_track", miss)
    monkeypatch.setattr(main, "can_resolve", lambda has_spotify: True)
    r = _post(client, room, "next", {"expected_seq": 0}).json()
    assert r["now_playing"]["track_id"] == f"yt-{YT[0]}"  # catalog misses are skipped
    assert len(calls) == main.MAX_RESOLVE_PER_SKIP


def test_resolver_caches_hits_and_misses(monkeypatch):
    resolve.reset_resolve_cache()
    calls = []

    async def fake_yt(q, limit=5):
        calls.append(q)
        return [{"youtube_id": "ccccccccccc", "album_art": None, "artist": "Chan"}]
    monkeypatch.setattr(resolve, "youtube_is_configured", lambda: True)
    monkeypatch.setattr(resolve, "spotify_is_configured", lambda: False)
    monkeypatch.setattr(resolve, "_youtube_budget_ok", lambda: True)
    monkeypatch.setattr(resolve, "youtube_search", fake_yt)
    for _ in range(2):
        hit = asyncio.run(resolve.resolve_track("p01", "Levitating", "Dua Lipa", has_spotify=False))
        assert hit == {"youtube_id": "ccccccccccc", "album_art": None}
    assert calls == ["Dua Lipa Levitating"]


def test_resolver_does_not_cache_when_over_the_youtube_budget(monkeypatch):
    resolve.reset_resolve_cache()
    monkeypatch.setattr(resolve, "youtube_is_configured", lambda: True)
    monkeypatch.setattr(resolve, "spotify_is_configured", lambda: False)
    monkeypatch.setattr(resolve, "_youtube_budget_ok", lambda: False)
    assert asyncio.run(resolve.resolve_track("p01", "a", "b", has_spotify=False)) is None
    assert resolve._cache == {}


def test_history_and_seq_survive_a_restart(client, room, tmp_path):
    _post(client, room, "play", {"track_id": f"yt-{YT[0]}"})
    _post(client, room, "next", {"expected_seq": 1})
    store = RoomStore(tmp_path / "r.json", 3600)
    store.save(PARTIES)
    restored = store.load()[room]
    assert restored.history == [f"yt-{YT[0]}"]
    assert restored.now_playing.seq == 2 and restored.now_playing.source == "youtube"


# Spotify token lifetime

def test_callback_records_token_expiry(client, party_code, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    async def fake_exchange(code):
        return {"access_token": "A1", "refresh_token": "R1", "expires_in": 3600}
    monkeypatch.setattr(main, "exchange_code_for_token", fake_exchange)
    url = client.post(f"/party/{party_code}/spotify/login-url", headers=host_headers(party_code)).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    client.get(f"/auth/spotify/callback?code=x&state={state}", follow_redirects=False)
    tok = client.get(f"/party/{party_code}/spotify-token", headers=host_headers(party_code)).json()
    assert tok["token"] == "A1"
    assert 3500 < tok["expires_at"] - main.time.time() <= 3600


def test_refresh_replaces_token_and_expiry(client, party_code, monkeypatch):
    PARTIES[party_code].spotify_token = "OLD"
    PARTIES[party_code].spotify_refresh = "R1"

    async def fake_refresh(rt):
        assert rt == "R1"
        return {"access_token": "NEW", "expires_in": 3600}
    monkeypatch.setattr(main, "refresh_spotify_token", fake_refresh)
    r = client.post(f"/party/{party_code}/refresh-token", headers=host_headers(party_code))
    assert r.status_code == 200 and r.json()["token"] == "NEW"
    assert PARTIES[party_code].spotify_token == "NEW"
    assert PARTIES[party_code].spotify_refresh == "R1"  # Spotify may not send a new one
    assert r.json()["expires_at"] > main.time.time() + 3000


def test_refresh_failure_is_a_clear_error(client, party_code, monkeypatch):
    PARTIES[party_code].spotify_token = "OLD"
    PARTIES[party_code].spotify_refresh = "REVOKED"

    async def boom(rt):
        raise RuntimeError("invalid_grant")
    monkeypatch.setattr(main, "refresh_spotify_token", boom)
    r = client.post(f"/party/{party_code}/refresh-token", headers=host_headers(party_code))
    assert r.status_code == 502
    assert PARTIES[party_code].spotify_token == "OLD"
