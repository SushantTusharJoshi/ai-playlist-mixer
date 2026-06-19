from __future__ import annotations
import secrets, string, uuid, time
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.agents.fairness_agent import FairnessAgent
from app.agents.profile_agent import ProfileAgent
from app.agents.ranking_agent import RankingAgent
from app.agents.voting_agent import VotingAgent
from app.config import settings
from app.data import AVAILABLE_GENRES, GENRE_DEFAULTS, PARTIES, TRACK_CATALOG, tracks_for_genre
from app.ml.features import cluster_guests, user_similarity_matrix
from app.models.schemas import (
    ClusterInfo, CreatePartyRequest, JoinRequest, NowPlaying, NowPlayingRequest,
    PartySession, QueueItem, SearchRequest, Track, UserProfile, VoteRequest,
)
from app.services.spotify import build_spotify_login_url, exchange_code_for_token, refresh_spotify_token
from app.services.spotify_search import spotify_is_configured, spotify_search

app = FastAPI(title="AI Playlist Mixer", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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

def _qi(q: QueueItem) -> dict:
    return {"track_id":q.track.id,"name":q.track.name,"artist":q.track.artist,"genres":q.track.genres,
            "score":q.score,"votes":q.votes,"reasons":q.reasons,"matched_users":q.matched_users,
            "energy":q.track.energy,"danceability":q.track.danceability,"popularity":q.track.popularity,
            "uri":q.track.uri,"album_art":q.track.album_art}

# ── Health ────────────────────────────────────────
@app.get("/health")
def health():
    return {"ok":True,"v":"1.0.0","spotify":spotify_is_configured(),"ai":llm_agent is not None}

@app.get("/genres")
def list_genres():
    return {"genres":AVAILABLE_GENRES}

# ── Party ─────────────────────────────────────────
@app.post("/party/create")
def create_party(req: CreatePartyRequest):
    code = _code()
    PARTIES[code] = PartySession(code=code, host_id=req.host_id, theme=req.theme)
    return PARTIES[code]

@app.get("/party/{code}")
def get_party(code: str):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    return PARTIES[code]

@app.get("/party/{code}/poll")
def poll(code: str):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    p = PARTIES[code]
    return {
        "code":p.code,
        "members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members],
        "queue":[_qi(q) for q in p.queue],
        "ai_summary":p.ai_summary,
        "cluster_info":p.cluster_info.model_dump() if p.cluster_info else None,
        "now_playing":p.now_playing.model_dump(),
        "has_spotify":bool(p.spotify_token),
    }

# ── Join ──────────────────────────────────────────
@app.post("/party/{code}/join")
def join(code: str, req: JoinRequest):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    genre = req.genre.lower().strip()
    if genre not in GENRE_DEFAULTS: raise HTTPException(400, f"Pick from: {AVAILABLE_GENRES}")
    p = PARTIES[code]
    d = GENRE_DEFAULTS[genre]
    uid = f"user-{uuid.uuid4().hex[:8]}"
    u = UserProfile(id=uid, display_name=req.display_name.strip(), source="custom", genre=genre,
                    top_genres=d["related"][:3], preferred_energy=d["energy"],
                    preferred_danceability=d["danceability"], candidate_tracks=tracks_for_genre(genre, 12))
    p.members.append(u)
    return {"user_id":uid, "members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members]}

# ── Generate Queue ────────────────────────────────
@app.post("/party/{code}/generate-queue")
async def generate_queue(code: str):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    p = PARTIES[code]
    if not p.members: raise HTTPException(400, "Add guests first")

    votes = voting_agent.get_votes(code)
    p.queue = ranking_agent.rank(p.members, votes=votes)

    cr = cluster_guests(p.members)
    p.cluster_info = ClusterInfo(clusters={str(k):v for k,v in cr["clusters"].items()},
                                  n_clusters=cr["n_clusters"],
                                  cluster_genres={str(k):v for k,v in cr["cluster_genres"].items()})

    if llm_agent:
        p.ai_summary = await llm_agent.summarize_party_taste(p.members, p.queue)
    else:
        gs = set()
        for u in p.members: gs.update(u.top_genres)
        p.ai_summary = f"Party of {len(p.members)} guests across {', '.join(sorted(gs)[:5])}. Queue balanced with ML fairness ranking."

    return {"queue":[_qi(q) for q in p.queue],"members":[{"id":m.id,"display_name":m.display_name,"genre":m.genre} for m in p.members],
            "ai_summary":p.ai_summary,"cluster_info":p.cluster_info.model_dump() if p.cluster_info else None,
            "similarity":user_similarity_matrix(p.members)}

# ── Vote ──────────────────────────────────────────
@app.post("/party/{code}/vote")
def vote(code: str, req: VoteRequest):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    p = PARTIES[code]
    votes = voting_agent.vote(code, req.track_id, req.value)
    # Just update vote counts on existing queue items, don't rebuild
    for q in p.queue:
        q.votes = votes.get(q.track.id, 0)
    # Re-sort by score + vote boost without wiping the queue
    for q in p.queue:
        base = q.score - (min(max(q.votes - req.value, -5), 5) * 0.04)  # remove old boost
        q.score = round(base + (min(max(q.votes, -5), 5) * 0.04), 4)    # add new boost
    p.queue.sort(key=lambda x: x.score, reverse=True)
    return {"queue":[_qi(q) for q in p.queue]}

# ── Add Track ─────────────────────────────────────
@app.post("/party/{code}/add-track")
def add_track(code: str, track: Track, added_by: str = ""):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    p = PARTIES[code]
    if any(q.track.id == track.id for q in p.queue):
        return {"added":False,"reason":"duplicate"}
    reason = f"added by {added_by}" if added_by else "added by search"
    p.queue.append(QueueItem(track=track, score=0.5, reasons=[reason], votes=0, matched_users=[]))
    return {"added":True,"queue_length":len(p.queue)}

# ── Now Playing ───────────────────────────────────
@app.post("/party/{code}/now-playing")
def set_now_playing(code: str, req: NowPlayingRequest):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    data = req.model_dump()
    data["started_at"] = time.time()
    PARTIES[code].now_playing = NowPlaying(**data)
    return {"ok":True}

@app.post("/party/{code}/stop-playing")
def stop_playing(code: str):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    PARTIES[code].now_playing = NowPlaying()
    return {"ok":True}

# ── Search ────────────────────────────────────────

# ── Queue Next (insert after current) ────────────────────────
@app.post("/party/{code}/queue-next")
def queue_next(code: str, track: Track, added_by: str = ""):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    p = PARTIES[code]
    # Don't add duplicates
    if any(q.track.id == track.id for q in p.queue):
        return {"added": False, "reason": "duplicate"}
    reason = f"queued by {added_by}" if added_by else "queued next"
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
    q = req.query.lower().strip()
    if not q:
        return {"results": [], "source": "none"}

    all_results = []
    source = "local"

    # Spotify (leave room for YouTube results)
    if spotify_is_configured():
        try:
            sp_limit = req.limit - 3 if req.limit > 5 else max(req.limit - 2, 3)
            sp = await spotify_search(q, limit=sp_limit)
            all_results.extend(sp)
            source = "spotify"
        except Exception as e:
            print(f"Spotify error: {e}")

    # YouTube
    try:
        from app.services.youtube import youtube_search as yt_search, youtube_is_configured
        if youtube_is_configured():
            yt = await yt_search(q, limit=5)
            for y in yt:
                all_results.append(y)
            source = source + "+youtube" if source != "local" else "youtube"
    except Exception as e:
        print(f"YouTube error: {e}")

    # Local fallback
    if not all_results:
        local = [t.model_dump() for t in TRACK_CATALOG.values() if q in t.name.lower() or q in t.artist.lower() or any(q in g.lower() for g in t.genres)]
        local.sort(key=lambda t: t.get("popularity", 0), reverse=True)
        return {"results": local[:req.limit], "source": "local"}

    return {"results": all_results[:req.limit], "source": source}

@app.get("/auth/spotify/login")
def spotify_login(party_code: str = ""):
    state = f"{party_code}:{secrets.token_urlsafe(8)}"
    return RedirectResponse(build_spotify_login_url(state))

@app.get("/auth/spotify/callback")
async def spotify_callback(code: str | None = None, state: str = "", error: str | None = None):
    if error: raise HTTPException(400, error)
    if not code: raise HTTPException(400, "Missing code")
    token_data = await exchange_code_for_token(code)
    party_code = state.split(":")[0] if ":" in state else ""
    if party_code and party_code in PARTIES:
        PARTIES[party_code].spotify_token = token_data.get("access_token", "")
        PARTIES[party_code].spotify_refresh = token_data.get("refresh_token", "")
    redirect_url = f"{settings.frontend_url}/host/{party_code}?spotify=connected"
    return RedirectResponse(redirect_url)

@app.get("/party/{code}/spotify-token")
def get_spotify_token(code: str):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    t = PARTIES[code].spotify_token
    if not t: return {"token":None}
    return {"token":t}

@app.post("/party/{code}/refresh-token")
async def do_refresh_token(code: str):
    if code not in PARTIES: raise HTTPException(404, "Party not found")
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
    if code not in PARTIES: raise HTTPException(404, "Party not found")
    items = sorted(PARTIES[code].queue, key=lambda q: q.votes, reverse=True)
    return {"leaderboard":[{"rank":i+1,**_qi(q)} for i,q in enumerate(items) if q.votes != 0]}
