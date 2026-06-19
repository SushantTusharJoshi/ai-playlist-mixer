"""
Spotify search using Client Credentials flow.
No user login needed. Gives access to the entire 100M+ track catalog.
"""
from __future__ import annotations

import base64
import time

import httpx

from app.config import settings

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"

# Cache the token so we don't request one per search
_token_cache: dict = {"token": "", "expires_at": 0}


async def _get_client_token() -> str:
    """
    Client Credentials flow: app-level token, no user login.
    Valid for 1 hour. We cache it.
    """
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    credentials = f"{settings.spotify_client_id}:{settings.spotify_client_secret}"
    b64_credentials = base64.b64encode(credentials.encode()).decode()

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            SPOTIFY_TOKEN_URL,
            headers={
                "Authorization": f"Basic {b64_credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        data = resp.json()

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return _token_cache["token"]


async def spotify_search(query: str, limit: int = 20) -> list[dict]:
    """
    Search Spotify's entire catalog.
    Returns normalized track dicts matching your Track schema.
    """
    token = await _get_client_token()

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SPOTIFY_API_URL}/search",
            params={"q": query, "type": "track", "limit": limit},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    tracks = []
    for item in data.get("tracks", {}).get("items", []):
        tracks.append({
            "id": f"sp-{item['id']}",
            "name": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "genres": [],  # track-level genres need a separate artist lookup
            "energy": 0.5,  # need audio-features endpoint for real values
            "danceability": 0.5,
            "popularity": item.get("popularity", 50) / 100,
            "uri": item.get("uri"),
            "album_art": item["album"]["images"][0]["url"] if item["album"]["images"] else None,
        })

    return tracks


async def spotify_audio_features(track_ids: list[str]) -> dict[str, dict]:
    """
    Batch fetch audio features (energy, danceability, etc.) for tracks.
    Spotify allows up to 100 IDs per request.
    """
    # Strip our 'sp-' prefix to get Spotify IDs
    clean_ids = [tid.replace("sp-", "") for tid in track_ids[:100]]
    if not clean_ids:
        return {}

    token = await _get_client_token()

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{SPOTIFY_API_URL}/audio-features",
            params={"ids": ",".join(clean_ids)},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()

    features = {}
    for af in data.get("audio_features", []):
        if af:
            features[f"sp-{af['id']}"] = {
                "energy": af.get("energy", 0.5),
                "danceability": af.get("danceability", 0.5),
                "valence": af.get("valence", 0.5),
                "tempo": af.get("tempo", 120),
            }
    return features


def spotify_is_configured() -> bool:
    return bool(settings.spotify_client_id and settings.spotify_client_secret)
