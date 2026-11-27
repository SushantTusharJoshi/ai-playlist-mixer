from __future__ import annotations

import secrets
import string
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.agents.fairness_agent import FairnessAgent
from app.agents.profile_agent import ProfileAgent
from app.agents.ranking_agent import RankingAgent
from app.agents.voting_agent import VotingAgent, vote_boost
from app.config import settings
from app.data import AVAILABLE_GENRES, GENRE_DEFAULTS, PARTIES, tracks_for_genre
from app.ml.features import cluster_guests, user_similarity_matrix
from app.models.schemas import (
    ClusterInfo,
    CreatePartyRequest,
    JoinRequest,
    NowPlaying,
    NowPlayingRequest,
    PartySession,
    QueueItem,
    SearchRequest,
    Track,
    UserProfile,
    VoteRequest,
)
from app.persistence import STATE_LOCK, RoomStore, mutates
from app.services.search import search_all
from app.services.spotify import build_spotify_login_url, exchange_code_for_token, refresh_spotify_token
from app.services.spotify_search import spotify_is_configured

room_store = RoomStore(settings.room_state_path or None, settings.room_idle_ttl_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Restart recovery: rebuild live parties from the last saved file.
    restored = room_store.load()
    with STATE_LOCK:
        PARTIES.update(restored)
    if restored:
        print(f"Restored {len(restored)} parties from {room_store.path}")
    yield
    await run_in_threadpool(room_store.save, PARTIES)


app = FastAPI(title="AI Playlist Mixer", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        settings.frontend_url,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

profile_agent = ProfileAgent()
ranking_agent = RankingAgent()
fairness_agent = FairnessAgent()
voting_agent = VotingAgent()

llm_agent = None
try:
    from app.agents.llm_agent import LLMAgent
    llm_agent = LLMAgent()
except Exception:
    pass

def _code(n=6):
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))

# ── Access control ────────────────────────────────
# The party code is shared with every guest (it is in the share link), so it
# only grants guest actions. Host-only actions need the host key that
# /party/create returns to the creating device. Guest votes and additions
# need the user key that /join returns.
SECRET_FIELDS = {"spotify_token", "spotify_refresh", "host_key", "member_keys", "vote_choices"}

def _party(code: str) -> PartySession:
    p = PARTIES.get(code)
    if p is None: raise HTTPException(404, "Party not found")
    return p

def _is_host(p: PartySession, host_key: str | None) -> bool:
    return bool(host_key and p.host_key and secrets.compare_digest(host_key, p.host_key))

def _require_host(p: PartySession, host_key: str | None) -> None:
    if not _is_host(p, host_key):
        raise HTTPException(403, "Host key required")

def _actor(p: PartySession, host_key: str | None, user_key: str | None) -> tuple[str, str]:
    """(voter id, display name) for the host or a joined guest; 401 otherwise."""
    if _is_host(p, host_key):
        return "host", "Host"
    uid = p.member_keys.get(user_key or "")
    if uid:
        name = next((m.display_name for m in p.members if m.id == uid), "Guest")
        return uid, name
    raise HTTPException(401, "Join the party first")

def _public(p: PartySession) -> dict:
    return p.model_dump(exclude=SECRET_FIELDS)

# OAuth state values issued by /spotify/login-url: state -> (party code, expires at)
OAUTH_STATE_TTL = 600
_OAUTH_STATES: dict[str, tuple[str, float]] = {}

def _store() -> RoomStore:
    return room_store

def _qi(q: QueueItem) -> dict:
    return {"track_id":q.track.id,"name":q.track.name,"artist":q.track.artist,"genres":q.track.genres,
            "score":q.score,"votes":q.votes,"reasons":q.reasons,"matched_users":q.matched_users,
            "energy":q.track.energy,"danceability":q.track.danceability,"popularity":q.track.popularity,
            "uri":q.track.uri,"album_art":q.track.album_art}

# ── Health ────────────────────────────────────────
@app.get("/health")
def health():
    return {"ok":True,"v":"1.0.0","spotify":spotify_is_configured(),"ai":llm_agent is not None,
            "persistence":room_store.enabled}

@app.get("/genres")
def list_genres():
    return {"genres":AVAILABLE_GENRES}

# ── Party ─────────────────────────────────────────
@app.post("/party/create")
@mutates(_store, PARTIES)
def create_party(req: CreatePartyRequest):
    room_store.expire_idle(PARTIES)
    if len(PARTIES) >= settings.max_parties:
        raise HTTPException(503, "Too many live parties, try again later")
    code = _code()
    while code in PARTIES:
        code = _code()
    PARTIES[code] = PartySession(code=code, host_id=req.host_id[:40], theme=req.theme[:80],
                                 host_key=secrets.token_urlsafe(24))
    return {**_public(PARTIES[code]), "host_key": PARTIES[code].host_key}

@app.get("/party/{code}")
def get_party(code: str):
    return _public(_party(code))

@app.get("/party/{code}/poll")
def poll(code: str):
    with STATE_LOCK:
        p = _party(code)
        p.last_active_at = time.time()  # polling devices keep the party alive; not saved on its own
        return {
            "code":p.code,
            "members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members],
            "queue":[_qi(q) for q in p.queue],
            "ai_summary":p.ai_summary,
            "cluster_info":p.cluster_info.model_dump() if p.cluster_info else None,
            "now_playing":p.now_playing.model_dump(),
            "has_spotify":bool(p.spotify_token),
        }

MAX_DEVICES = 7

# ── Join ──────────────────────────────────────────
@app.post("/party/{code}/join")
@mutates(_store, PARTIES)
def join(code: str, req: JoinRequest):
    p = _party(code)
    genre = req.genre.lower().strip()
    if genre not in GENRE_DEFAULTS: raise HTTPException(400, f"Pick from: {AVAILABLE_GENRES}")
    display_name = " ".join(req.display_name.split())
    if not display_name: raise HTTPException(400, "Enter a name")
    if len(p.members) >= MAX_DEVICES:
        raise HTTPException(400, f"Party is full ({MAX_DEVICES} devices max)")
    d = GENRE_DEFAULTS[genre]
    uid = f"user-{uuid.uuid4().hex[:8]}"
    user_key = secrets.token_urlsafe(16)
    u = UserProfile(id=uid, display_name=display_name, source="custom", genre=genre,
                    top_genres=d["related"][:3], preferred_energy=d["energy"],
                    preferred_danceability=d["danceability"], candidate_tracks=tracks_for_genre(genre, 12))
    u = profile_agent.normalize_dummy_user(u)
    p.members.append(u)
    p.member_keys[user_key] = uid
    return {"user_id":uid, "user_key":user_key, "members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members]}

# ── Generate Queue ────────────────────────────────
@app.post("/party/{code}/generate-queue")
async def generate_queue(code: str, x_host_key: str | None = Header(None)):
    with STATE_LOCK:
        p = _party(code)
        _require_host(p, x_host_key)
        if not p.members: raise HTTPException(400, "Add guests first")

        votes = voting_agent.get_votes(p)
        p.queue = ranking_agent.rank(p.members, votes=votes)
        p.queue = fairness_agent.rerank(p.queue)

        cr = cluster_guests(p.members)
        p.cluster_info = ClusterInfo(clusters={str(k):v for k,v in cr["clusters"].items()},
                                      n_clusters=cr["n_clusters"],
                                      cluster_genres={str(k):v for k,v in cr["cluster_genres"].items()})
        members, queue = list(p.members), list(p.queue)

    # The LLM call runs without the lock so votes and polls are not held up.
    SUMMARY_COOLDOWN = 30
    if llm_agent and (time.time() - p.last_summary_at >= SUMMARY_COOLDOWN or not p.ai_summary):
        summary = await llm_agent.summarize_party_taste(members, queue)
        with STATE_LOCK:
            p.ai_summary = summary
            p.last_summary_at = time.time()
    elif not llm_agent:
        gs = set()
        for u in members: gs.update(u.top_genres)
        p.ai_summary = f"Party of {len(members)} guests across {', '.join(sorted(gs)[:5])}. Queue balanced with ML fairness ranking."

    with STATE_LOCK:
        p.last_active_at = time.time()
        body = {"queue":[_qi(q) for q in p.queue],"members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members],
                "ai_summary":p.ai_summary,"cluster_info":p.cluster_info.model_dump() if p.cluster_info else None,
                "similarity":user_similarity_matrix(p.members)}
    await run_in_threadpool(room_store.save, PARTIES)
    return body

# ── Vote ──────────────────────────────────────────
@app.post("/party/{code}/vote")
@mutates(_store, PARTIES)
def vote(code: str, req: VoteRequest, x_host_key: str | None = Header(None), x_user_key: str | None = Header(None)):
    p = _party(code)
    voter, _ = _actor(p, x_host_key, x_user_key)
    item = next((q for q in p.queue if q.track.id == req.track_id), None)
    if item is None: raise HTTPException(404, "Track is not in the queue")
    try:
        voting_agent.vote(p, req.track_id, req.value, voter)
    except ValueError:
        raise HTTPException(400, "You already voted on this track") from None
    # Only the voted track moves: swap its old clamped boost for the new one.
    old_votes, item.votes = item.votes, p.votes.get(req.track_id, 0)
    item.score = round(item.score - vote_boost(old_votes) + vote_boost(item.votes), 4)
    p.queue.sort(key=lambda x: x.score, reverse=True)
    return {"queue":[_qi(q) for q in p.queue]}

# ── Add Track ─────────────────────────────────────
@app.post("/party/{code}/add-track")
@mutates(_store, PARTIES)
def add_track(code: str, track: Track, added_by: str = Query("", max_length=40),
              x_host_key: str | None = Header(None), x_user_key: str | None = Header(None)):
    p = _party(code)
    _, who = _actor(p, x_host_key, x_user_key)  # the name comes from the server, not added_by
    if any(q.track.id == track.id for q in p.queue):
        return {"added":False,"reason":"duplicate"}
    if len(p.queue) >= settings.max_queue:
        raise HTTPException(400, f"Queue is full ({settings.max_queue} tracks max)")
    reason = f"added by {who}"
    p.queue.append(QueueItem(track=track, score=0.5, reasons=[reason], votes=0, matched_users=[]))
    return {"added":True,"queue_length":len(p.queue)}

# ── Now Playing ───────────────────────────────────
@app.post("/party/{code}/now-playing")
@mutates(_store, PARTIES)
def set_now_playing(code: str, req: NowPlayingRequest, x_host_key: str | None = Header(None)):
    _require_host(_party(code), x_host_key)
    data = req.model_dump()
    data["started_at"] = time.time()
    PARTIES[code].now_playing = NowPlaying(**data)
    return {"ok":True}

@app.post("/party/{code}/stop-playing")
@mutates(_store, PARTIES)
def stop_playing(code: str, x_host_key: str | None = Header(None)):
    _require_host(_party(code), x_host_key)
    PARTIES[code].now_playing = NowPlaying()
    return {"ok":True}

# ── Search ────────────────────────────────────────

# ── Queue Next (insert after current) ────────────────────────
@app.post("/party/{code}/queue-next")
@mutates(_store, PARTIES)
def queue_next(code: str, track: Track, added_by: str = Query("", max_length=40),
               x_host_key: str | None = Header(None), x_user_key: str | None = Header(None)):
    p = _party(code)
    _, who = _actor(p, x_host_key, x_user_key)  # the name comes from the server, not added_by
    # Don't add duplicates
    if any(q.track.id == track.id for q in p.queue):
        return {"added": False, "reason": "duplicate"}
    if len(p.queue) >= settings.max_queue:
        raise HTTPException(400, f"Queue is full ({settings.max_queue} tracks max)")
    reason = f"queued by {who}"
    item = QueueItem(track=track, score=0.99, reasons=[reason], votes=0, matched_users=[])
    # Find currently playing track and insert after it
    np_idx = -1
    for i, q in enumerate(p.queue):
        if q.track.id == p.now_playing.track_id:
            np_idx = i
            break
    if np_idx >= 0:
        p.queue.insert(np_idx + 1, item)
    else:
        p.queue.insert(0, item)  # If nothing playing, put at top
    return {"added": True, "position": np_idx + 1, "queue_length": len(p.queue)}

@app.post("/search")
async def search_tracks(req: SearchRequest):
    return await search_all(req.query, req.limit)

@app.post("/party/{code}/spotify/login-url")
def spotify_login_url(code: str, x_host_key: str | None = Header(None)):
    """Start Spotify sign-in for this party. The state is a single-use server nonce."""
    _require_host(_party(code), x_host_key)
    now = time.time()
    for k in [k for k, (_, exp) in _OAUTH_STATES.items() if exp < now]:
        _OAUTH_STATES.pop(k, None)
    state = secrets.token_urlsafe(24)
    _OAUTH_STATES[state] = (code, now + OAUTH_STATE_TTL)
    return {"url": build_spotify_login_url(state)}

@app.get("/auth/spotify/callback")
async def spotify_callback(code: str | None = None, state: str = "", error: str | None = None):
    pending = _OAUTH_STATES.pop(state, None) if state else None
    if not pending or pending[1] < time.time():
        raise HTTPException(400, "Invalid or expired sign-in, start again from the host page")
    party_code = pending[0]
    if error or not code:
        return RedirectResponse(f"{settings.frontend_url}/host/{party_code}?spotify=error")
    token_data = await exchange_code_for_token(code)
    if party_code in PARTIES:
        PARTIES[party_code].spotify_token = token_data.get("access_token", "")
        PARTIES[party_code].spotify_refresh = token_data.get("refresh_token", "")
    redirect_url = f"{settings.frontend_url}/host/{party_code}?spotify=connected"
    return RedirectResponse(redirect_url)

@app.get("/party/{code}/spotify-token")
def get_spotify_token(code: str, x_host_key: str | None = Header(None)):
    _require_host(_party(code), x_host_key)
    t = PARTIES[code].spotify_token
    if not t: return {"token":None}
    return {"token":t}

@app.post("/party/{code}/refresh-token")
async def do_refresh_token(code: str, x_host_key: str | None = Header(None)):
    _require_host(_party(code), x_host_key)
    rt = PARTIES[code].spotify_refresh
    if not rt: raise HTTPException(400, "No refresh token")
    data = await refresh_spotify_token(rt)
    PARTIES[code].spotify_token = data.get("access_token", "")
    if data.get("refresh_token"):
        PARTIES[code].spotify_refresh = data["refresh_token"]
    return {"token":PARTIES[code].spotify_token}

# ── Leaderboard ───────────────────────────────────
@app.get("/party/{code}/leaderboard")
def leaderboard(code: str):
    items = sorted(_party(code).queue, key=lambda q: q.votes, reverse=True)
    return {"leaderboard":[{"rank":i+1,**_qi(q)} for i,q in enumerate(items) if q.votes != 0]}
