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

from app import playback
from app.agents.fairness_agent import FairnessAgent, reorder_after_vote
from app.agents.llm_agent import LLMAgent, build_summary_prompt, summary_key
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
    PlaybackRequest,
    PlayRequest,
    QueueItem,
    SearchRequest,
    SkipRequest,
    Track,
    UserProfile,
    VoteRequest,
)
from app.persistence import STATE_LOCK, RoomStore, mutates
from app.services.resolve import can_resolve, resolve_track
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
    llm_agent = LLMAgent()
except Exception as e:
    print(f"LLM agent disabled: {e}")

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
            "uri":q.track.uri,"album_art":q.track.album_art,"youtube_id":playback.youtube_id_of(q.track)}

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
        resolvable = can_resolve(bool(p.spotify_token))
        return {
            "code":p.code,
            "members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members],
            "queue":[_qi(q) for q in p.queue],
            "ai_summary":p.ai_summary,
            "cluster_info":p.cluster_info.model_dump() if p.cluster_info else None,
            "now_playing":p.now_playing.model_dump(),
            "has_spotify":bool(p.spotify_token),
            # Catalog tracks can be matched to Spotify (host signed in) or YouTube (API key set).
            "can_resolve":resolvable,
            "prev_track_id":p.history[-1] if p.history else None,
            "up_next_track_id":playback.peek_next(p, bool(p.spotify_token), resolvable),
        }

MAX_DEVICES = 7

# ── Join ──────────────────────────────────────────
# What it does: adds a guest to a party by its 6-character code and hands back a secret user key.
# Catch it: "The party code is in a public link. What can someone do with only the code?"
# Card: docs/cards/party-join.md
@app.post("/party/{code}/join")
@mutates(_store, PARTIES)
def join(code: str, req: JoinRequest):
    # STEP: find the party; an unknown code is a 404
    p = _party(code)
    # DECISION: genre must be one we have defaults for, and the name must not be blank
    genre = req.genre.lower().strip()
    if genre not in GENRE_DEFAULTS: raise HTTPException(400, f"Pick from: {AVAILABLE_GENRES}")
    display_name = " ".join(req.display_name.split())
    if not display_name: raise HTTPException(400, "Enter a name")
    # DECISION: at most 7 devices (checked under STATE_LOCK, so parallel joins cannot overshoot)
    if len(p.members) >= MAX_DEVICES:
        raise HTTPException(400, f"Party is full ({MAX_DEVICES} devices max)")
    # STEP: build the guest's taste profile from the genre defaults
    d = GENRE_DEFAULTS[genre]
    uid = f"user-{uuid.uuid4().hex[:8]}"
    user_key = secrets.token_urlsafe(16)
    u = UserProfile(id=uid, display_name=display_name, source="custom", genre=genre,
                    top_genres=d["related"][:3], preferred_energy=d["energy"],
                    preferred_danceability=d["danceability"], candidate_tracks=tracks_for_genre(genre, 12))
    u = profile_agent.normalize_dummy_user(u)
    p.members.append(u)
    p.member_keys[user_key] = uid
    # RETURN: the public id plus the secret key this device sends on votes and additions
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
        now_playing = p.now_playing.model_copy()

    if llm_agent:
        await _refresh_summary(p, members, queue, now_playing)
    else:
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

SUMMARY_COOLDOWN = 30  # seconds between LLM calls for one party


_summary_in_flight: set[str] = set()


# What it does: refreshes the AI party summary only when its inputs changed and the cooldown allows.
# Catch it: "How do you keep LLM cost bounded when the host keeps clicking Generate?"
# Card: docs/cards/summary-cache.md
async def _refresh_summary(p: PartySession, members, queue, now_playing) -> str:
    """Decide cached / cooldown / call, and call the LLM at most once per cooldown."""
    # STEP: key = hash of the exact prompt (guests, tastes, top of queue in order, now playing)
    key = summary_key(build_summary_prompt(members, queue, now_playing))
    with STATE_LOCK:
        # DECISION: same key as the stored summary, so skip the call
        if p.ai_summary and key == p.summary_key:
            return "cached"  # nothing the model would see has changed
        # DECISION: inside the 30 s cooldown, keep the old text
        if p.ai_summary and time.time() - p.last_summary_at < SUMMARY_COOLDOWN:
            return "cooldown"  # changed, but too soon: keep the old text, the key stays stale
        if p.code in _summary_in_flight:
            return "in_flight"  # a parallel request is already asking the model
        _summary_in_flight.add(p.code)
    try:
        # STEP: call providers in order (Groq, OpenAI, Bedrock) without the lock; the reply is sanitized
        summary = await llm_agent.summarize_party_taste(members, queue, now_playing)
        # STEP: store text, key and time together
        with STATE_LOCK:
            p.ai_summary = summary
            p.summary_key = key
            p.last_summary_at = time.time()
    finally:
        _summary_in_flight.discard(p.code)
    # RETURN: what happened, for tests and logs
    return "called"


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
    p.queue = reorder_after_vote(p.queue)
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
# The server's now_playing is the one source of truth for what the room plays.
# Every track change bumps now_playing.seq; the host page loads media when seq
# changes and guests follow it read-only.

def _np_reply(p: PartySession, changed: bool) -> dict:
    return {"changed": changed, "now_playing": p.now_playing.model_dump(),
            "prev_track_id": p.history[-1] if p.history else None}

def _stale(p: PartySession, expected_seq: int | None) -> bool:
    return expected_seq is not None and expected_seq != p.now_playing.seq

MAX_RESOLVE_PER_SKIP = 3  # bound the upstream searches one Next press can cause

async def _choose(p: PartySession, candidates: list[QueueItem], has_spotify: bool) -> tuple[QueueItem, str] | None:
    """First candidate this host can play, matching catalog tracks to a source on the way."""
    tries = 0
    for item in candidates:
        src = playback.source_of(item.track, has_spotify)
        if src:
            return item, src
        if not playback.needs_resolving(item.track) or tries >= MAX_RESOLVE_PER_SKIP or not can_resolve(has_spotify):
            continue
        tries += 1
        t = item.track
        found = await resolve_track(t.id, t.name, t.artist, has_spotify)
        if not found:
            continue
        with STATE_LOCK:
            # A copy: queue items share Track objects with the catalog and other parties.
            update = {k: found[k] for k in ("uri", "youtube_id") if found.get(k)}
            if found.get("album_art") and not t.album_art:
                update["album_art"] = found["album_art"]
            item.track = t = t.model_copy(update=update)
        src = playback.source_of(t, has_spotify)
        if src:
            return item, src
    return None

async def _commit(p: PartySession, body: dict) -> dict:
    p.last_active_at = time.time()
    await run_in_threadpool(room_store.save, PARTIES)
    return body

@app.post("/party/{code}/play")
async def play_track(code: str, req: PlayRequest, x_host_key: str | None = Header(None)):
    """Host picked a track in the queue."""
    with STATE_LOCK:
        p = _party(code)
        _require_host(p, x_host_key)
        item = playback.find(p.queue, req.track_id)
        if item is None: raise HTTPException(404, "Track is not in the queue")
        has_spotify = bool(p.spotify_token)
    choice = await _choose(p, [item], has_spotify)
    if choice is None:
        raise HTTPException(409, "No playable source for this track: connect Spotify, or add it from a YouTube result")
    with STATE_LOCK:
        playback.set_track(p, *choice, push_current=True)
        body = _np_reply(p, True)
    return await _commit(p, body)

# What it does: advances the room to the next playable track, once, even if a track-end event and a tap race.
# Catch it: "The track ends and the host taps Next at the same moment. How do you not skip two tracks?"
# Card: docs/cards/player.md
@app.post("/party/{code}/next")
async def play_next(code: str, req: SkipRequest, x_host_key: str | None = Header(None)):
    with STATE_LOCK:
        p = _party(code)
        _require_host(p, x_host_key)
        # DECISION: the client was looking at an older track, so this skip already happened
        if _stale(p, req.expected_seq):
            return _np_reply(p, False)
        seq = p.now_playing.seq
        has_spotify = bool(p.spotify_token)
        # STEP: unplayed tracks after the current one, then the ones before it
        candidates = playback.next_candidates(p, req.shuffle)
    # STEP: first one this host can play (catalog tracks are matched to a source, at most 3 searches)
    choice = await _choose(p, candidates, has_spotify)
    wrapped = False
    if choice is None and req.repeat:
        # DECISION: repeat is on and everything was played, so start the queue over
        with STATE_LOCK:
            again = list(p.queue)
        if req.shuffle:
            playback.random.shuffle(again)
        choice = await _choose(p, again, has_spotify)
        wrapped = choice is not None
    with STATE_LOCK:
        # DECISION: someone else changed the track while we searched
        if p.now_playing.seq != seq:
            return _np_reply(p, False)
        if choice is None:
            # RETURN: queue finished; the room shows it ended
            playback.end_queue(p)
        else:
            if wrapped:
                p.history.clear()
            playback.set_track(p, *choice)
        body = _np_reply(p, True)
    return await _commit(p, body)

@app.post("/party/{code}/prev")
@mutates(_store, PARTIES)
def play_prev(code: str, req: SkipRequest, x_host_key: str | None = Header(None)):
    p = _party(code)
    _require_host(p, x_host_key)
    if _stale(p, req.expected_seq):
        return _np_reply(p, False)
    prev = playback.pop_previous(p, bool(p.spotify_token))
    if prev:
        playback.set_track(p, *prev, push_current=False)  # the current track is not played yet, Next returns to it
    elif p.now_playing.track_id:
        playback.restart(p)  # nothing earlier: start this one again
    else:
        return _np_reply(p, False)
    return _np_reply(p, True)

@app.post("/party/{code}/playback")
@mutates(_store, PARTIES)
def set_playback(code: str, req: PlaybackRequest, x_host_key: str | None = Header(None)):
    """Pause, resume, seek, or report the duration of the current track."""
    p = _party(code)
    _require_host(p, x_host_key)
    if req.seq != p.now_playing.seq or not p.now_playing.track_id:
        return _np_reply(p, False)  # about a track that is no longer current
    playback.set_position(p, req.is_playing, req.position_ms, req.duration_ms)
    return _np_reply(p, True)

@app.post("/party/{code}/now-playing")
@mutates(_store, PARTIES)
def set_now_playing(code: str, req: NowPlayingRequest, x_host_key: str | None = Header(None)):
    """Older direct form: the host names the track. Kept for compatibility; /play is preferred."""
    p = _party(code)
    _require_host(p, x_host_key)
    item = playback.find(p.queue, req.track_id) or QueueItem(
        track=Track(id=req.track_id, name=req.name, artist=req.artist, uri=req.uri,
                    album_art=req.album_art, youtube_id=req.youtube_id), score=0)
    src = playback.source_of(item.track, True) or ""
    playback.set_track(p, item, src)
    p.now_playing.is_playing = req.is_playing
    return {"ok":True}

@app.post("/party/{code}/stop-playing")
@mutates(_store, PARTIES)
def stop_playing(code: str, x_host_key: str | None = Header(None)):
    p = _party(code)
    _require_host(p, x_host_key)
    p.now_playing = NowPlaying(seq=p.now_playing.seq + 1, updated_at=time.time())
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

# What it does: finishes Spotify sign-in and stores the host's token on the party that started it.
# Catch it: "What is the OAuth state parameter for, and what breaks if you skip checking it?"
# Card: docs/cards/oauth-callback.md
@app.get("/auth/spotify/callback")
async def spotify_callback(code: str | None = None, state: str = "", error: str | None = None):
    # STEP: pop the state; it is single use, so a replay finds nothing
    pending = _OAUTH_STATES.pop(state, None) if state else None
    # DECISION: unknown or expired state is rejected before anything touches Spotify
    if not pending or pending[1] < time.time():
        raise HTTPException(400, "Invalid or expired sign-in, start again from the host page")
    party_code = pending[0]  # from the server, never from the URL
    # DECISION: the host declined or Spotify sent an error
    if error or not code:
        return RedirectResponse(f"{settings.frontend_url}/host/{party_code}?spotify=error")
    # STEP: swap the code for tokens and keep them in memory only
    token_data = await exchange_code_for_token(code)
    if party_code in PARTIES:
        PARTIES[party_code].spotify_token = token_data.get("access_token", "")
        PARTIES[party_code].spotify_refresh = token_data.get("refresh_token", "")
        PARTIES[party_code].spotify_expires_at = time.time() + int(token_data.get("expires_in", 3600))
    # RETURN: back to the host page
    redirect_url = f"{settings.frontend_url}/host/{party_code}?spotify=connected"
    return RedirectResponse(redirect_url)

@app.get("/party/{code}/spotify-token")
def get_spotify_token(code: str, x_host_key: str | None = Header(None)):
    p = _party(code)
    _require_host(p, x_host_key)
    if not p.spotify_token: return {"token":None}
    return {"token":p.spotify_token, "expires_at":p.spotify_expires_at}

# What it does: swaps the host's refresh token for a new access token before the old one expires.
# Catch it: "Spotify access tokens last an hour. What keeps a three-hour party playing?"
# Card: docs/cards/player.md
@app.post("/party/{code}/refresh-token")
async def do_refresh_token(code: str, x_host_key: str | None = Header(None)):
    p = _party(code)
    _require_host(p, x_host_key)
    rt = p.spotify_refresh
    if not rt: raise HTTPException(400, "No refresh token")
    try:
        data = await refresh_spotify_token(rt)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", "")
        print(f"Spotify refresh failed: {type(e).__name__} {status}")
        raise HTTPException(502, "Spotify refresh failed, connect Spotify again") from None
    with STATE_LOCK:
        p.spotify_token = data.get("access_token", "")
        p.spotify_expires_at = time.time() + int(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            p.spotify_refresh = data["refresh_token"]
        return {"token":p.spotify_token, "expires_at":p.spotify_expires_at}

# ── Leaderboard ───────────────────────────────────
@app.get("/party/{code}/leaderboard")
def leaderboard(code: str):
    items = sorted(_party(code).queue, key=lambda q: q.votes, reverse=True)
    return {"leaderboard":[{"rank":i+1,**_qi(q)} for i,q in enumerate(items) if q.votes != 0]}
