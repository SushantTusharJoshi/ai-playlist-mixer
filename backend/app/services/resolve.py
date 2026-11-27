"""
Find a playable source for a track this host cannot play yet:
- a catalog track from Generate Queue (no Spotify uri, no video id);
- a Spotify search result when the host has not connected Spotify.

- Host connected to Spotify: one Spotify search with the app token.
- Otherwise: one YouTube search by artist and title, inside the shared
  per-minute YouTube budget (a search costs 100 of the 10,000 daily units).
Real answers, including "nothing found", are cached per track id and source.
A search that could not run (budget used up, API error) raises
ResolveUnavailable and is not cached, so the track is not skipped for it.
"""
from __future__ import annotations

from app.services.search import _youtube_budget_ok
from app.services.spotify_search import spotify_is_configured, spotify_search
from app.services.youtube import youtube_is_configured, youtube_search

_cache: dict[tuple[str, str], dict | None] = {}


class ResolveUnavailable(Exception):
    """The search could not run right now; try again later."""


def _want(has_spotify: bool) -> str:
    return "spotify" if has_spotify and spotify_is_configured() else "youtube"


def cached(track_id: str, has_spotify: bool) -> tuple[bool, dict | None]:
    """(known, answer): known is False when this track was never searched."""
    key = (track_id, _want(has_spotify))
    return (key in _cache), _cache.get(key)


def can_resolve(has_spotify: bool) -> bool:
    return (has_spotify and spotify_is_configured()) or youtube_is_configured()


def reset_resolve_cache() -> None:
    _cache.clear()


async def resolve_track(track_id: str, name: str, artist: str, has_spotify: bool) -> dict | None:
    """{"uri", "album_art"} or {"youtube_id", "album_art"}; None when the search found nothing.

    Raises ResolveUnavailable when the search could not run.
    """
    want = _want(has_spotify)
    key = (track_id, want)
    if key in _cache:
        return _cache[key]
    found: dict | None = None
    try:
        if want == "spotify":
            hits = await spotify_search(f"track:{name} artist:{artist}", limit=1)
            if hits and hits[0].get("uri"):
                found = {"uri": hits[0]["uri"], "album_art": hits[0].get("album_art")}
        else:
            if not youtube_is_configured():
                return None  # nothing to search with; can_resolve() is False here anyway
            if not _youtube_budget_ok():
                raise ResolveUnavailable("YouTube search budget used up for this minute")
            hits = await youtube_search(f"{artist} {name}", limit=1)
            vid = hits[0].get("youtube_id") if hits else None
            if vid:
                found = {"youtube_id": vid, "album_art": hits[0].get("album_art")}
            elif hits and hits[0].get("artist") == "YouTube Search":
                raise ResolveUnavailable("YouTube search failed")  # the search-link fallback means the API errored
    except ResolveUnavailable:
        raise
    except Exception as e:
        print(f"Resolve error: {type(e).__name__}")
        raise ResolveUnavailable("search failed") from None
    _cache[key] = found
    return found
