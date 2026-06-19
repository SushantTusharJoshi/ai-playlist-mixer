"""YouTube Data API v3 search for music fallback."""
import urllib.parse
import httpx
from app.config import settings

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


async def youtube_search(query: str, limit: int = 5) -> list[dict]:
    """Search YouTube for music videos. Returns playable results."""
    key = getattr(settings, 'youtube_api_key', '')
    if not key:
        return [_fallback_result(query)]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(YOUTUBE_SEARCH_URL, params={
                "part": "snippet",
                "q": f"{query} official audio",
                "type": "video",
                "videoCategoryId": "10",  # Music category
                "maxResults": limit,
                "key": key,
            })
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", []):
            vid = item["id"].get("videoId", "")
            snippet = item.get("snippet", {})
            results.append({
                "id": f"yt-{vid}",
                "name": snippet.get("title", "Unknown"),
                "artist": snippet.get("channelTitle", ""),
                "genres": [],
                "energy": 0.5,
                "danceability": 0.5,
                "popularity": 0.5,
                "uri": None,
                "album_art": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                "youtube_id": vid,
                "youtube_url": f"https://www.youtube.com/watch?v={vid}",
                "youtube_embed": f"https://www.youtube.com/embed/{vid}",
            })
        return results
    except Exception as e:
        print(f"YouTube API error: {e}")
        return [_fallback_result(query)]


def _fallback_result(query: str) -> dict:
    """Fallback when no API key: just generate a search URL."""
    q = urllib.parse.quote(query)
    return {
        "id": f"yt-search-{q[:20]}",
        "name": query,
        "artist": "YouTube Search",
        "genres": [],
        "energy": 0.5,
        "danceability": 0.5,
        "popularity": 0.5,
        "uri": None,
        "album_art": None,
        "youtube_id": None,
        "youtube_url": f"https://www.youtube.com/results?search_query={q}",
        "youtube_embed": None,
    }


def youtube_search_url(name: str, artist: str) -> str:
    q = urllib.parse.quote(f"{artist} {name} official audio")
    return f"https://www.youtube.com/results?search_query={q}"


def youtube_is_configured() -> bool:
    return bool(getattr(settings, 'youtube_api_key', ''))
