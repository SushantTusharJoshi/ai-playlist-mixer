import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# Length caps keep guest-supplied text small: it is shown on every device
# every 3 seconds and display names reach the LLM prompt.
class Track(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    name: str = Field(max_length=300)
    artist: str = Field(max_length=300)
    genres: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list, max_length=10)
    energy: float = 0.5
    danceability: float = 0.5
    popularity: float = 0.5
    uri: str | None = Field(default=None, max_length=300)
    album_art: str | None = Field(default=None, max_length=1000)

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
    youtube_id: str | None = None
    is_playing: bool = False
    started_at: float = 0

class PartySession(BaseModel):
    code: str
    host_id: str
    theme: str = "balanced party"
    members: list[UserProfile] = Field(default_factory=list)
    queue: list[QueueItem] = Field(default_factory=list)
    cluster_info: ClusterInfo | None = None
    ai_summary: str = ""
    last_summary_at: float = 0
    summary_key: str = ""  # hash of the prompt behind ai_summary
    now_playing: NowPlaying = Field(default_factory=NowPlaying)
    spotify_token: str = ""
    spotify_refresh: str = ""
    # Secret returned only to the device that created the party. Host-only
    # endpoints (playback, queue generation, Spotify token) require it.
    host_key: str = ""
    # Per-guest secrets handed out on join: user_key -> user_id.
    member_keys: dict[str, str] = Field(default_factory=dict)
    # Net votes per track, and each voter's current choice ("voter|track" -> -1 or 1).
    votes: dict[str, int] = Field(default_factory=dict)
    vote_choices: dict[str, int] = Field(default_factory=dict)
    # Last time anyone polled or changed this party; drives idle expiry.
    last_active_at: float = Field(default_factory=time.time)

class CreatePartyRequest(BaseModel):
    host_id: str = "host-dev"
    theme: str = "balanced party"

class JoinRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)
    genre: str = Field(max_length=40)

class JoinDummyRequest(BaseModel):
    dummy_user_id: str

class VoteRequest(BaseModel):
    track_id: str
    value: Literal[-1, 1]
    voted_by: str = ""

class SearchRequest(BaseModel):
    query: str = Field(max_length=100)
    limit: int = Field(default=20, ge=1, le=20)

class NowPlayingRequest(BaseModel):
    track_id: str = Field(max_length=120)
    name: str = Field(max_length=300)
    artist: str = Field(max_length=300)
    uri: str | None = Field(default=None, max_length=300)
    album_art: str | None = Field(default=None, max_length=1000)
    youtube_id: str | None = Field(default=None, max_length=32)
    is_playing: bool = True
    started_at: float = 0
