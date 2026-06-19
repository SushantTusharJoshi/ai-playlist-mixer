from typing import Literal
from pydantic import BaseModel, Field

class Track(BaseModel):
    id: str
    name: str
    artist: str
    genres: list[str] = Field(default_factory=list)
    energy: float = 0.5
    danceability: float = 0.5
    popularity: float = 0.5
    uri: str | None = None
    album_art: str | None = None

class UserProfile(BaseModel):
    id: str
    display_name: str
    source: Literal["custom", "dummy", "spotify"] = "custom"
    genre: str = ""
    top_genres: list[str] = Field(default_factory=list)
    top_artists: list[str] = Field(default_factory=list)
    preferred_energy: float = 0.5
    preferred_danceability: float = 0.5
    candidate_tracks: list[Track] = Field(default_factory=list)

class QueueItem(BaseModel):
    track: Track
    score: float
    reasons: list[str] = Field(default_factory=list)
    votes: int = 0
    matched_users: list[str] = Field(default_factory=list)

class ClusterInfo(BaseModel):
    clusters: dict[str, list[str]] = Field(default_factory=dict)
    n_clusters: int = 0
    cluster_genres: dict[str, list[str]] = Field(default_factory=dict)

class NowPlaying(BaseModel):
    track_id: str = ""
    name: str = ""
    artist: str = ""
    uri: str | None = None
    album_art: str | None = None
    is_playing: bool = False

class PartySession(BaseModel):
    code: str
    host_id: str
    theme: str = "balanced party"
    members: list[UserProfile] = Field(default_factory=list)
    queue: list[QueueItem] = Field(default_factory=list)
    cluster_info: ClusterInfo | None = None
    ai_summary: str = ""
    now_playing: NowPlaying = Field(default_factory=NowPlaying)
    spotify_token: str = ""
    spotify_refresh: str = ""

class CreatePartyRequest(BaseModel):
    host_id: str = "host-dev"
    theme: str = "balanced party"

class JoinRequest(BaseModel):
    display_name: str
    genre: str

class JoinDummyRequest(BaseModel):
    dummy_user_id: str

class VoteRequest(BaseModel):
    track_id: str
    value: Literal[-1, 1]

class SearchRequest(BaseModel):
    query: str
    limit: int = 20

class NowPlayingRequest(BaseModel):
    track_id: str
    name: str
    artist: str
    uri: str | None = None
    album_art: str | None = None
    is_playing: bool = True
