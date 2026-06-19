# AI Playlist Mixer v1.0 — Production

## Quick Start (Local)

### Backend
```bash
cd backend
cp .env.example .env   # Add your Spotify + Claude keys
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install && npm run dev
```

Open http://localhost:3000

## Routes
- `/` — Landing (create or join)
- `/host/CODE` — Host dashboard (queue, playback, search, voting)
- `/party/CODE` — Guest view (join, search, vote)
- `/admin/CODE` — ML insights (clusters, scores, formula)

## Deploy to Production

### Backend → Render (free)
1. Push to GitHub
2. New Web Service on render.com
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`
5. Add env vars (Spotify keys, Claude key, FRONTEND_URL)

### Frontend → Vercel (free)
1. `npm install -g vercel && vercel`
2. Set `NEXT_PUBLIC_API_BASE` to your Render URL

### Update Spotify
Add your production callback URL in Spotify dashboard:
`https://your-backend.onrender.com/auth/spotify/callback`

## Cost: Under $1/month
