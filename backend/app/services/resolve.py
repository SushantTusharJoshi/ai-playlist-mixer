"""
Find a playable source for a catalog track (a Generate Queue track has no
Spotify uri and no video id, so before this nothing in it could play).

- Host connected to Spotify: one Spotify search with the app token.
- Otherwise: one YouTube search, inside the shared per-minute YouTube budget
  (a search costs 100 of the 10,000 daily quota units).
Answers, including misses, are cached per track id and source.
"""
from __future__ import annotations

from app.services.search import _youtube_budget_ok
from app.services.spotify_search import spotify_is_configured, spotify_search
from app.services.youtube import youtube_is_configured, youtube_search

_cache: dict[tuple[str, str], dict | None] = {}


def can_resolve(has_spotify: bool) -> bool:
    return (has_spotify and spotify_is_configured()) or youtube_is_configured()


def reset_resolve_cache() -> None:
    _cache.clear()


async def resolve_track(track_id: str, name: str, artist: str, has_spotify: bool) -> dict | None:
    """{"uri", "album_art"} or {"youtube_id", "album_art"}, or None when nothing was found."""
    want = "spotify" if has_spotify and spotify_is_configured() else "youtube"
    key = (track_id, want)
    if key in _cache:
        return _cache[key]
    found: dict | None = None
    try:
        if want == "spotify":
            hits = await spotify_search(f"track:{name} artist:{artist}", limit=1)
            if hits and hits[0].get("uri"):
                found = {"uri": hits[0]["uri"], "album_art": hits[0].get("album_art")}
        elif youtube_is_configured():
            if not _youtube_budget_ok():
                return None  # over budget: not cached, try again later
            hits = await youtube_search(f"{artist} {name}", limit=1)
            vid = hits[0].get("youtube_id") if hits else None
            if vid:
                found = {"youtube_id": vid, "album_art": hits[0].get("album_art")}
            elif hits and hits[0].get("artist") == "YouTube Search":
                return None  # the API failed and returned the search-link fallback: do not cache
    except Exception as e:
        print(f"Resolve error: {type(e).__name__}")
        return None
    _cache[key] = found
    return found
