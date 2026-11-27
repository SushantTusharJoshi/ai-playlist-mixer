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


def test_next_bounds_upstream_searches_without_skipping_unsearched_tracks(client, room, monkeypatch):
    calls = []

    async def miss(track_id, name, artist, has_spotify):
        calls.append(track_id)
        resolve._cache[(track_id, "youtube")] = None  # what the real resolver stores for "nothing found"
        return None
    monkeypatch.setattr(main, "resolve_track", miss)
    monkeypatch.setattr(main, "can_resolve", lambda has_spotify: True)
    catalog = [q.track.id for q in PARTIES[room].queue if not q.track.id.startswith("yt-")]
    first = _post(client, room, "next", {"expected_seq": 0})
    assert first.status_code == 503  # 3 searches used, the 4th track was not searched: do not skip it
    assert len(calls) == main.MAX_RESOLVE_PER_SKIP and _np(client, room)["seq"] == 0
    for _ in range(10):
        r = _post(client, room, "next", {"expected_seq": 0})
        if r.status_code == 200:
            break
    assert r.json()["now_playing"]["track_id"] == f"yt-{YT[0]}"
    assert calls == catalog  # every catalog track searched exactly once; misses come from the cache


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
    with pytest.raises(resolve.ResolveUnavailable):
        asyncio.run(resolve.resolve_track("p01", "a", "b", has_spotify=False))
    assert resolve._cache == {}


def test_resolver_does_not_cache_a_failed_youtube_call(monkeypatch):
    resolve.reset_resolve_cache()

    async def fallback(q, limit=5):
        return [{"youtube_id": None, "artist": "YouTube Search"}]  # what youtube_search returns on an API error
    monkeypatch.setattr(resolve, "youtube_is_configured", lambda: True)
    monkeypatch.setattr(resolve, "spotify_is_configured", lambda: False)
    monkeypatch.setattr(resolve, "_youtube_budget_ok", lambda: True)
    monkeypatch.setattr(resolve, "youtube_search", fallback)
    with pytest.raises(resolve.ResolveUnavailable):
        asyncio.run(resolve.resolve_track("p01", "a", "b", has_spotify=False))
    assert resolve._cache == {}


# Spotify search results on a host that has not connected Spotify (the production repro, party CDZ174)

SP = [("sp-1", "Blinding Lights", "The Weeknd"), ("sp-2", "Blinding Lights (Remix)", "The Weeknd, ROSALIA")]


@pytest.fixture()
def spotify_only_room(client, party_with_member, monkeypatch):
    """No generated queue: only two Spotify results, no Spotify login, YouTube key set."""
    code, _ = party_with_member
    for tid, name, artist in SP:
        client.post(f"/party/{code}/add-track", headers=host_headers(code),
                    json={"id": tid, "name": name, "artist": artist, "uri": f"spotify:track:{tid[3:]}"})
    resolve.reset_resolve_cache()
    searches = []

    async def fake_yt(q, limit=5):
        searches.append(q)
        vid = {"The Weeknd Blinding Lights": "4NRXx6U8ABQ"}.get(q, "fHI8X4OXluQ")
        return [{"youtube_id": vid, "album_art": f"https://i.ytimg.com/vi/{vid}/hq.jpg", "artist": "chan"}]
    monkeypatch.setattr(resolve, "youtube_is_configured", lambda: True)
    monkeypatch.setattr(resolve, "spotify_is_configured", lambda: True)  # search uses the app token
    monkeypatch.setattr(resolve, "_youtube_budget_ok", lambda: True)
    monkeypatch.setattr(resolve, "youtube_search", fake_yt)
    return code, searches


def test_poll_offers_spotify_results_for_youtube_matching(client, spotify_only_room):
    code, _ = spotify_only_room
    poll = client.get(f"/party/{code}/poll").json()
    assert poll["has_spotify"] is False and poll["can_resolve"] is True
    assert poll["up_next_track_id"] == "sp-1"


def test_bar_play_with_nothing_playing_matches_a_spotify_track_to_youtube(client, spotify_only_room):
    code, searches = spotify_only_room
    r = _post(client, code, "next", {"expected_seq": 0, "repeat": True})  # what the bar Play button sends
    np = r.json()["now_playing"]
    assert r.status_code == 200 and np["ended"] is False
    assert np["track_id"] == "sp-1" and np["source"] == "youtube" and np["youtube_id"] == "4NRXx6U8ABQ"
    assert np["uri"] is None  # the YouTube player plays it, not Spotify
    assert searches == ["The Weeknd Blinding Lights"]
    item = client.get(f"/party/{code}/poll").json()["queue"][0]
    assert item["uri"] == "spotify:track:1" and item["youtube_id"] == "4NRXx6U8ABQ"  # both kept


def test_row_play_matches_and_the_match_is_reused(client, spotify_only_room):
    code, searches = spotify_only_room
    assert _post(client, code, "play", {"track_id": "sp-2"}).json()["now_playing"]["source"] == "youtube"
    assert _post(client, code, "play", {"track_id": "sp-1"}).json()["now_playing"]["youtube_id"] == "4NRXx6U8ABQ"
    assert _post(client, code, "play", {"track_id": "sp-2"}).status_code == 200
    assert len(searches) == 2  # one search per track, then stored on the queue item


def test_next_and_previous_match_too(client, spotify_only_room):
    code, searches = spotify_only_room
    _post(client, code, "play", {"track_id": "sp-1"})
    nxt = _post(client, code, "next", {"expected_seq": 1}).json()["now_playing"]
    assert nxt["track_id"] == "sp-2" and nxt["source"] == "youtube"
    # Previous to a track whose stored match is gone (for example matched in an older process): it is matched again
    PARTIES[code].queue[0].track = PARTIES[code].queue[0].track.model_copy(update={"youtube_id": None})
    resolve.reset_resolve_cache()
    back = _post(client, code, "prev", {"expected_seq": 2}).json()["now_playing"]
    assert back["track_id"] == "sp-1" and back["source"] == "youtube"
    assert PARTIES[code].history == []


def test_a_track_is_skipped_only_when_the_search_finds_nothing(client, spotify_only_room, monkeypatch):
    code, _ = spotify_only_room

    async def none_for_first(q, limit=5):
        return [] if "Remix" not in q else [{"youtube_id": "fHI8X4OXluQ", "album_art": None, "artist": "c"}]
    monkeypatch.setattr(resolve, "youtube_search", none_for_first)
    np = _post(client, code, "next", {"expected_seq": 0}).json()["now_playing"]
    assert np["track_id"] == "sp-2"


def test_busy_search_does_not_skip_or_end_the_queue(client, spotify_only_room, monkeypatch):
    code, _ = spotify_only_room
    monkeypatch.setattr(resolve, "_youtube_budget_ok", lambda: False)
    r = _post(client, code, "next", {"expected_seq": 0, "repeat": True})
    assert r.status_code == 503 and "try again" in r.json()["detail"]
    np = _np(client, code)
    assert np["seq"] == 0 and np["ended"] is False and PARTIES[code].history == []
    assert _post(client, code, "play", {"track_id": "sp-1"}).status_code == 503


def test_connected_host_plays_the_spotify_uri_without_searching(client, spotify_only_room):
    code, searches = spotify_only_room
    PARTIES[code].spotify_token = "ACCESS"
    np = _post(client, code, "play", {"track_id": "sp-1"}).json()["now_playing"]
    assert np["source"] == "spotify" and np["uri"] == "spotify:track:1"
    assert searches == []


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
