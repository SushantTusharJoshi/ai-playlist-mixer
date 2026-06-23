# AI Playlist Mixer

A real-time collaborative music platform where multiple users across devices vote, queue, and listen to the same playlist simultaneously — powered by Spotify, YouTube, and Groq AI.

**Live:** [ai-playlist-mixer.vercel.app](https://ai-playlist-mixer.vercel.app) · **Backend:** [Railway](https://ai-playlist-mixer-production.up.railway.app)

---

## What It Does Differently

Most music apps are single-user. This one is built for a room. One host creates a party, up to 7 devices join as guests, and the queue is democratically shaped in real time — every vote, skip, and addition is instantly reflected across all connected clients. The AI reads the room and generates a live "party taste summary" based on what the group has actually been playing.

---

## Spotify and YouTube. Finally Under One Roof.

This is the part nobody has built cleanly.

Spotify has the catalog and the Premium playback SDK. YouTube has everything Spotify doesn't — every obscure track, every live version, every song that never got a streaming license.

Most apps pick one. This one unifies both into a single queue.

A host searches Spotify. A guest adds a YouTube track. They sit side by side in the same playlist, play in sequence, and sync across all 7 devices without either platform knowing about the other. The backend abstracts the source — every track is just a track, regardless of where it came from.

For Premium Spotify users, the Web Playback SDK handles full in-browser audio. For everyone else — guests, free-tier users, non-Spotify users — YouTube fills the gap silently. No friction. No "this track isn't available." Just music.

That's the actual unlock: **the room works for everyone in it, regardless of what subscriptions they have.**

---

## Key Features

### Multi-Device Party Sync
- Supports up to **7 simultaneous devices** in a single party session
- Cross-user YouTube sync uses server-stored `started_at` timestamps so late-joining guests resume at the correct position — not from the beginning
- 3-second poll keeps all clients in sync without WebSockets

### Fairness-Weighted Queue
- Votes (upvote/downvote) feed a fairness reranking agent that prevents one user from dominating the queue
- Queue-next lets any guest bump a track to play immediately after the current one

### Groq AI Party Summary
- Uses `llama-3.1-70b-versatile` (free tier) to analyze the session's played tracks and generate a natural-language "party taste" description
- Falls back to a static summary if the Groq key is not set

### Playback Controls
- Prev/next navigation using `useRef` (not `useState`) to avoid stale closure bugs in React polling loops
- Scrubber/seek, shuffle, and repeat modes
- Host controls playback; guests see synchronized read-only player state

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15, React 19, Tailwind CSS |
| Backend | FastAPI, Python 3.12 |
| Music | Spotify Web Playback SDK, YouTube Data API v3 |
| AI | Groq API (llama-3.1-70b-versatile) |
| Auth | Spotify OAuth 2.0 |
| Deploy | Railway (backend) + Vercel (frontend) |

---

## SEO & Traffic Architecture

Every shared party link is a dynamic, indexable route (`/party/[code]`). When a host shares that link, up to 6 other guests join — each one a distinct traffic event with behavioral data attached: what they played, how long they stayed, what they voted on.

The host's app doesn't just get listeners. It gets a dataset. Each guest session maps:

```
inbound traffic source → in-app behavior → taste signal → model improvement
```

The host controls the room. The guests improve the model.

Specific implementation:
- **Open Graph tags** on party join pages so shared links render rich previews on social platforms — each link is a user-generated traffic entry point
- **Dynamic routes** (`/party/[code]`) pre-rendered with fallback so guest join pages are indexable
- **Session ID behavior mapping** — tracks played, votes cast, and session duration logged per device
- **Planned:** UTM parameter capture on join URLs to attribute traffic source per guest device — bridging SEO-driven inbound traffic to in-app behavioral data

---

## Known Logical Gaps (Planned Fixes)

These are real architectural limitations, not polish issues:

| Gap | Root Cause | Planned Fix |
|---|---|---|
| YouTube iframe reloads every 3s | Guest poll overwrites `ytVideoId` state even when track hasn't changed | Add equality check before updating state; only set if ID differs |
| YouTube audio stops when player is closed | YouTube embed requires visible iframe to maintain audio context | Migrate to YouTube IFrame API with programmatic `playVideo()` instead of embed |
| Groq summary fires on every poll | No debounce on AI summary generation | Gate behind explicit "Summarize" button or fire only on track change events |
| No persistent party history | Sessions exist only in memory; server restart wipes everything | Add PostgreSQL session persistence with TTL |
| Single-host failure | If host disconnects, party state becomes stale for guests | Promote guest to host via server-side host election on disconnect |
| Device limit is soft | The "7 devices" cap is not enforced server-side | Add server-side guest slot tracking with rejection on overflow |

---

## Local Setup

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export SPOTIFY_CLIENT_ID=your_id
export SPOTIFY_CLIENT_SECRET=your_secret
export GROQ_API_KEY=your_groq_key
export YOUTUBE_API_KEY=your_youtube_key
export FRONTEND_URL=http://localhost:3000
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

Add to your Spotify app dashboard redirect URIs:
```
http://localhost:8000/auth/spotify/callback
```

---

## Deployment

Backend → Railway, Frontend → Vercel. Set `NEXT_PUBLIC_API_BASE` on Vercel to your Railway URL.

---

## GitHub

[github.com/SushantTusharJoshi/ai-playlist-mixer](https://github.com/SushantTusharJoshi/ai-playlist-mixer)
