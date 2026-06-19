"""Spotify OAuth with streaming scopes for Web Playback SDK."""
import base64
from urllib.parse import urlencode
import httpx
from app.config import settings

SCOPES = "streaming user-read-playback-state user-modify-playback-state user-top-read user-read-recently-played playlist-modify-public"

def build_spotify_login_url(state: str) -> str:
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": SCOPES,
        "state": state,
        "show_dialog": "true",
    }
    return f"https://accounts.spotify.com/authorize?{urlencode(params)}"

async def exchange_code_for_token(code: str) -> dict:
    creds = base64.b64encode(f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": settings.spotify_redirect_uri},
        )
        resp.raise_for_status()
        return resp.json()

async def refresh_spotify_token(refresh_token: str) -> dict:
    creds = base64.b64encode(f"{settings.spotify_client_id}:{settings.spotify_client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()
