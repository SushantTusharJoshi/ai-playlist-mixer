"""
Search fan-out: Spotify (app token) + YouTube + local catalog fallback.

Every guest keystroke (after a 300 ms debounce) can become a search, and the
endpoint needs no party code. Two guards bound the upstream cost:
- a short TTL cache, so the same query is not sent upstream again;
- an app-wide YouTube budget per minute (a YouTube search costs 100 quota
  units of a 10,000 per day default), after which search skips YouTube.
"""
from __future__ import annotations

import time
from collections import OrderedDict, deque

from app.config import settings
from app.data import TRACK_CATALOG
from app.services.spotify_search import spotify_is_configured, spotify_search
from app.services.youtube import youtube_is_configured, youtube_search

CACHE_TTL_SECONDS = 600
CACHE_MAX_ENTRIES = 500

_cache: OrderedDict[tuple[str, int], tuple[float, dict]] = OrderedDict()
_youtube_calls: deque[float] = deque()


def _cache_get(key: tuple[str, int]) -> dict | None:
    hit = _cache.get(key)
    if not hit:
        return None
    stored_at, value = hit
    if time.time() - stored_at > CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return value


def _cache_put(key: tuple[str, int], value: dict) -> None:
    _cache[key] = (time.time(), value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


def _youtube_budget_ok(now: float | None = None) -> bool:
    """Sliding one-minute window shared by every caller of this process."""
    now = now or time.time()
    while _youtube_calls and now - _youtube_calls[0] > 60:
        _youtube_calls.popleft()
    if len(_youtube_calls) >= settings.youtube_calls_per_minute:
        return False
    _youtube_calls.append(now)
    return True


def reset_search_state() -> None:
    _cache.clear()
    _youtube_calls.clear()


def local_search(q: str, limit: int) -> list[dict]:
    local = [t.model_dump() for t in TRACK_CATALOG.values()
             if q in t.name.lower() or q in t.artist.lower() or any(q in g.lower() for g in t.genres)]
    local.sort(key=lambda t: t.get("popularity", 0), reverse=True)
    return local[:limit]


async def search_all(query: str, limit: int) -> dict:
    q = query.lower().strip()
    if not q:
        return {"results": [], "source": "none"}

    key = (q, limit)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    all_results: list[dict] = []
    source = "local"
    degraded = False  # an upstream failed or was skipped: do not cache this answer

    # Spotify (leave room for YouTube results)
    if spotify_is_configured():
        try:
            sp_limit = limit - 3 if limit > 5 else max(limit - 2, 3)
            all_results.extend(await spotify_search(q, limit=sp_limit))
            source = "spotify"
        except Exception as e:
            print(f"Spotify error: {e}")
            degraded = True

    # YouTube, within the app-wide budget
    if youtube_is_configured():
        if _youtube_budget_ok():
            try:
                all_results.extend(await youtube_search(q, limit=5))
                source = source + "+youtube" if source != "local" else "youtube"
            except Exception as e:
                print(f"YouTube error: {type(e).__name__}")
                degraded = True
        else:
            degraded = True

    # Local fallback
    if not all_results:
        result = {"results": local_search(q, limit), "source": "local"}
    else:
        result = {"results": all_results[:limit], "source": source}
    if not degraded:
        _cache_put(key, result)
    return result
