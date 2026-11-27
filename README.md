# AI Playlist Mixer

A real-time collaborative music platform where multiple users across devices vote, queue, and listen to the same playlist simultaneously — powered by Spotify, YouTube, and Groq AI.

**Backend:** [Railway](https://ai-playlist-mixer-production.up.railway.app)

---

## What It Does Differently

Most music apps are single-user. This one is built for a room. One host creates a party, up to 7 devices join as guests, and the queue is democratically shaped in real time — every vote, skip and addition reaches every device on the next 3-second poll. The AI reads the room and writes a "party taste summary" from the guests' tastes and the current queue.

---

## Spotify and YouTube. Finally Under One Roof.

Spotify has the catalog and the Premium playback SDK. YouTube has everything Spotify doesn't — every obscure track, every live version, every song that never got a streaming license.

Most apps pick one. This one unifies both into a single queue.

A host searches Spotify. A guest adds a YouTube track. They sit side by side in the same playlist, play in sequence, and sync across all 7 devices without either platform knowing about the other. The backend abstracts the source — every track is just a track, regardless of where it came from.

The host plays Spotify tracks in the browser through the Web Playback SDK, which needs Spotify Premium. Guests never sign in to Spotify: search runs on an app-level token, and YouTube and a local catalog cover tracks too. How playback behaves for a host on a free Spotify account has not been tested yet.

### Platform limits

Since March 9, 2026, Spotify apps in development mode need Premium and allow up to 5 authorized users ([Spotify](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security)). Only the host signs in, so the cap applies to hosts, not guests.

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
- Uses a Groq-hosted model (default `openai/gpt-oss-120b`, set with `GROQ_MODEL`) to describe the room's taste from the guests' genre and energy preferences and the top of the queue
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
| AI | Groq API (`openai/gpt-oss-120b` by default, `GROQ_MODEL` to change) |
| Auth | Spotify OAuth 2.0 |
| Deploy | Railway (backend) + Vercel (frontend) |

---

## Privacy

Party and host pages are private links: they send `noindex` in both a meta tag and an `X-Robots-Tag` header, so search engines do not list them.

---

## Known Logical Gaps (Planned Fixes)

These are real architectural limitations, not polish issues:

| Gap | Root Cause | Planned Fix |
|---|---|---|
| YouTube iframe reloads every 3s | Guest poll overwrites `ytVideoId` state even when track hasn't changed | Add equality check before updating state; only set if ID differs |
| YouTube audio stops when player is closed | YouTube embed requires visible iframe to maintain audio context | Migrate to YouTube IFrame API with programmatic `playVideo()` instead of embed |
| Summary refreshes on a timer | A 30-second cooldown limits calls, but the summary is not keyed to what changed in the room | Cache the summary on the full room state (guests, tastes, queue order, now playing) |
| Single-host failure | If host disconnects, party state becomes stale for guests | Promote guest to host via server-side host election on disconnect |

---

## Reliability

- Room state (guests, queue, votes, now playing) is saved to a JSON file after every change, at `ROOM_STATE_PATH` (default `data/rooms.json`). Writes go to a temp file in the same folder and are swapped in with `os.replace`, so a crash mid-write keeps the previous file. One write runs at a time.
- On startup the app loads that file, so a restart or redeploy keeps every live party. Spotify tokens are not saved: after a restart the host taps Connect Spotify again.
- Parties with no activity (no poll and no change) for `ROOM_IDLE_TTL_SECONDS` (default 6 hours) are dropped.
- Single instance only. State lives in one process's memory and one file; two workers or two replicas would each keep their own parties and overwrite each other's file. Keep one replica and one worker (`Procfile` uses `-w 1`).

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
