"""
Playback rules for one room: which source plays a track, what Next and
Previous pick, and how now playing changes. Pure functions over the party
state, so the HTTP routes stay thin and the rules are tested directly.

- The server's now_playing is the one source of truth. Every track change
  bumps now_playing.seq; clients load media when seq changes, never on a
  plain poll.
- history holds the track ids played before the current one. Next skips
  them; Previous pops the last one.
"""
from __future__ import annotations

import random
import re
import time

from app.models.schemas import NowPlaying, PartySession, QueueItem, Track

HISTORY_MAX = 200
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id_of(track: Track) -> str | None:
    """A real 11-character video id, or None.

    Ids like "yt-search-..." come from the no-key YouTube fallback and are a
    search link, not a video, so they are not playable.
    """
    if track.youtube_id and _YT_ID.match(track.youtube_id):
        return track.youtube_id
    if track.id.startswith("yt-"):
        vid = track.id[3:]
        if _YT_ID.match(vid):
            return vid
    return None


def source_of(track: Track, has_spotify: bool) -> str | None:
    """"spotify", "youtube", or None when this host cannot play the track."""
    if track.uri and track.uri.startswith("spotify:") and has_spotify:
        return "spotify"
    if youtube_id_of(track):
        return "youtube"
    return None


def needs_resolving(track: Track) -> bool:
    """Catalog tracks have neither a Spotify uri nor a video id."""
    return not track.uri and not youtube_id_of(track)


def find(queue: list[QueueItem], track_id: str) -> QueueItem | None:
    return next((q for q in queue if q.track.id == track_id), None)


def next_candidates(p: PartySession, shuffle: bool = False, rng: random.Random | None = None) -> list[QueueItem]:
    """Tracks Next may pick, best first.

    Order: the tracks after the current one in queue order, then the ones
    before it, so "Play next" (inserted right after the current track) comes
    first and votes that move tracks are respected. Played tracks and the
    current track are left out. Shuffle keeps the same set in random order.
    """
    current = p.now_playing.track_id
    played = set(p.history)
    idx = next((i for i, q in enumerate(p.queue) if q.track.id == current), -1)
    ordered = p.queue[idx + 1:] + p.queue[:max(idx, 0)] if idx >= 0 else list(p.queue)
    out = [q for q in ordered if q.track.id != current and q.track.id not in played]
    if shuffle:
        (rng or random).shuffle(out)
    return out


def set_track(p: PartySession, item: QueueItem, source: str, push_current: bool = True,
              now: float | None = None) -> NowPlaying:
    """Make item the current track, starting at 0, and bump seq."""
    now = time.time() if now is None else now
    old = p.now_playing
    if push_current and old.track_id and old.track_id != item.track.id:
        p.history.append(old.track_id)
        del p.history[:-HISTORY_MAX]
    t = item.track
    p.now_playing = NowPlaying(
        track_id=t.id, name=t.name, artist=t.artist, uri=t.uri if source == "spotify" else None,
        album_art=t.album_art, youtube_id=youtube_id_of(t) if source == "youtube" else None,
        is_playing=True, started_at=now, seq=old.seq + 1, source=source,
        position_ms=0, duration_ms=0, updated_at=now, ended=False,
    )
    return p.now_playing


def restart(p: PartySession, now: float | None = None) -> NowPlaying:
    """Previous with no history: play the current track again from 0."""
    now = time.time() if now is None else now
    np = p.now_playing
    p.now_playing = np.model_copy(update={"seq": np.seq + 1, "position_ms": 0, "is_playing": True,
                                          "started_at": now, "updated_at": now, "ended": False})
    return p.now_playing


def end_queue(p: PartySession, now: float | None = None) -> NowPlaying:
    """Nothing left to play: keep the last track on screen, stopped."""
    now = time.time() if now is None else now
    np = p.now_playing
    if np.track_id:
        p.history.append(np.track_id)
        del p.history[:-HISTORY_MAX]
    p.now_playing = NowPlaying(seq=np.seq + 1, ended=True, updated_at=now)
    return p.now_playing


def pop_previous(p: PartySession, has_spotify: bool) -> tuple[QueueItem, str] | None:
    """Pop history until a track that is still queued and playable; None if none."""
    while p.history:
        tid = p.history.pop()
        item = find(p.queue, tid)
        if item is None:
            continue
        src = source_of(item.track, has_spotify)
        if src:
            return item, src
    return None


def set_position(p: PartySession, is_playing: bool, position_ms: int, duration_ms: int,
                 now: float | None = None) -> NowPlaying:
    """Pause, resume or seek within the current track. seq does not change."""
    now = time.time() if now is None else now
    np = p.now_playing
    if duration_ms:
        position_ms = min(position_ms, duration_ms)
    p.now_playing = np.model_copy(update={
        "is_playing": is_playing, "position_ms": position_ms,
        "duration_ms": duration_ms or np.duration_ms, "updated_at": now,
        "started_at": now - position_ms / 1000,
    })
    return p.now_playing
