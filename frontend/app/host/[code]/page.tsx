'use client';
import { use, useEffect, useState, useCallback, useRef } from 'react';

const API = process.env.NEXT_PUBLIC_API_BASE || 'https://ai-playlist-mixer-production.up.railway.app';
async function api(path: string, opts?: RequestInit) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', ...opts?.headers }, cache: 'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function apiBase() { return API; }

declare global { interface Window { onSpotifyWebPlaybackSDKReady: () => void; Spotify: any; } }

export default function HostPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [members, setMembers] = useState<any[]>([]);
  const [queue, setQueue] = useState<any[]>([]);
  const [summary, setSummary] = useState('');
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [np, setNp] = useState<any>({ is_playing: false });
  const [npExpanded, setNpExpanded] = useState(false);
  const [hasSpotify, setHasSpotify] = useState(false);
  const [sq, setSq] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [showDrop, setShowDrop] = useState(false);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [src, setSrc] = useState('');
  const searchTimer = useRef<any>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const [player, setPlayer] = useState<any>(null);
  const [deviceId, setDeviceId] = useState('');
  const [spToken, setSpToken] = useState('');
  const [sdkReady, setSdkReady] = useState(false);
  const [sortBy, setSortBy] = useState<'score' | 'votes'>('score');
  const [repeatOn, setRepeatOn] = useState(false);
  const [shuffled, setShuffled] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const [ytVideoId, setYtVideoId] = useState('');
  const [ytSrc, setYtSrc] = useState('');
  const [ytMinimized, setYtMinimized] = useState(false);
  const posTimer = useRef<any>(null);
  const playingIdx = useRef(-1);

  useEffect(() => {
    if (ytVideoId) {
      const startOffset = np.started_at ? Math.floor((Date.now() / 1000) - np.started_at) : 0;
      setYtSrc('https://www.youtube.com/embed/' + ytVideoId + '?autoplay=1&rel=0&start=' + Math.max(startOffset, 0));
    } else {
      setYtSrc('');
    }
  }, [ytVideoId]);

  const poll = useCallback(async () => {
    try {
      const d = await api(`/party/${code}/poll`);
      setMembers(d.members || []);
      if (d.queue?.length) setQueue(d.queue);
      setSummary(d.ai_summary || '');
      setNp(d.now_playing || { is_playing: false });
      setHasSpotify(d.has_spotify || false);
      // YouTube sync: only update if track changed, never close user's player to watch
    } catch {}
  }, [code]);

  useEffect(() => { poll(); const i = setInterval(poll, 3000); return () => clearInterval(i); }, [poll]);
  useEffect(() => { const h = (e: MouseEvent) => { if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false); }; document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h); }, []);
  useEffect(() => { if (!player) return; posTimer.current = setInterval(async () => { try { const s = await player.getCurrentState(); if (s && !seeking) { setPosition(s.position); setDuration(s.duration); } } catch {} }, 1000); return () => clearInterval(posTimer.current); }, [player, seeking]);
  useEffect(() => { if (np.track_id && queue.length) { const i = queue.findIndex(q => q.track_id === np.track_id); if (i >= 0) playingIdx.current = i; } }, [queue, np.track_id]);

  useEffect(() => {
    if (!hasSpotify || sdkReady) return;
    api(`/party/${code}/spotify-token`).then(d => {
      if (!d.token) return; setSpToken(d.token);
      if (document.getElementById('spotify-sdk')) return;
      const s = document.createElement('script'); s.id = 'spotify-sdk'; s.src = 'https://sdk.scdn.co/spotify-player.js'; document.head.appendChild(s);
      window.onSpotifyWebPlaybackSDKReady = () => {
        const p = new window.Spotify.Player({ name: 'AI Playlist Mixer', getOAuthToken: (cb: any) => cb(d.token), volume: 0.8 });
        p.addListener('ready', ({ device_id }: any) => { setDeviceId(device_id); setSdkReady(true); });
        p.addListener('not_ready', () => setSdkReady(false));
        p.connect(); setPlayer(p);
      };
    }).catch(() => {});
  }, [hasSpotify, code, sdkReady]);

  async function playAt(idx: number) {
    const item = queue[idx];
    if (!item) return;
    playingIdx.current = idx;

    // YouTube track
    if (item.track_id?.startsWith('yt-')) {
      const vid = item.track_id.replace('yt-', '');
      // Don't auto-open embed - user clicks Watch to see it
      api(`/party/${code}/now-playing`, { method: 'POST', body: JSON.stringify({ track_id: item.track_id, name: item.name, artist: item.artist, uri: null, album_art: item.album_art, youtube_id: vid, is_playing: true }) }).catch(() => {});
      setNp({ track_id: item.track_id, name: item.name, artist: item.artist, album_art: item.album_art, youtube_id: vid, is_playing: true });
      return;
    }

    // Spotify track
    if (!sdkReady || !spToken || !item.uri) return;
    try {
      await fetch(`https://api.spotify.com/v1/me/player/play?device_id=${deviceId}`, { method: 'PUT', headers: { 'Authorization': `Bearer ${spToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ uris: [item.uri] }) });
      setYtVideoId('');
      await api(`/party/${code}/now-playing`, { method: 'POST', body: JSON.stringify({ track_id: item.track_id, name: item.name, artist: item.artist, uri: item.uri, album_art: item.album_art, youtube_id: null, is_playing: true }) });
      setNp({ track_id: item.track_id, name: item.name, artist: item.artist, album_art: item.album_art, uri: item.uri, is_playing: true });
      setPosition(0);
    } catch (e) { console.error('Play failed:', e); }
  }

  function playTrack(item: any) { const i = queue.findIndex(q => q.track_id === item.track_id); if (i >= 0) playAt(i); }
  async function togglePlay() { if (player) { await player.togglePlay(); setNp((p: any) => ({ ...p, is_playing: !p.is_playing })); } }
  function playPrev() { if (playingIdx.current > 0) playAt(playingIdx.current - 1); else if (player) player.seek(0).then(() => setPosition(0)); }
  function playNext() { if (playingIdx.current < queue.length - 1) playAt(playingIdx.current + 1); else if (repeatOn && queue.length > 0) playAt(0); }
  async function seekTo(ms: number) { if (player) { await player.seek(ms); setPosition(ms); } }
  function shuffleQueue() { const s = [...queue]; for (let i = s.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [s[i], s[j]] = [s[j], s[i]]; } setQueue(s); setShuffled(!shuffled); if (np.track_id) playingIdx.current = s.findIndex(q => q.track_id === np.track_id); }
  function fmt(ms: number) { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`; }

  function onSearch(val: string) { setSq(val); if (searchTimer.current) clearTimeout(searchTimer.current); if (!val.trim()) { setResults([]); setShowDrop(false); return; } searchTimer.current = setTimeout(async () => { try { const d = await api('/search', { method: 'POST', body: JSON.stringify({ query: val.trim(), limit: 10 }) }); setResults(d.results || []); setSrc(d.source || ''); setShowDrop(true); } catch {} }, 300); }

  async function addTrack(t: any) { try { const d = await api(`/party/${code}/add-track?added_by=Host`, { method: 'POST', body: JSON.stringify({ id: t.id, name: t.name, artist: t.artist, genres: t.genres || [], energy: t.energy || 0.5, danceability: t.danceability || 0.5, popularity: t.popularity || 0.5, uri: t.uri || null, album_art: t.album_art || null }) }); if (d.added) { setAdded(p => new Set(p).add(t.id)); poll(); } } catch {} }
  async function queueNext(t: any) { try { const d = await api(`/party/${code}/queue-next?added_by=Host`, { method: 'POST', body: JSON.stringify({ id: t.id, name: t.name, artist: t.artist, genres: t.genres || [], energy: t.energy || 0.5, danceability: t.danceability || 0.5, popularity: t.popularity || 0.5, uri: t.uri || null, album_art: t.album_art || null }) }); if (d.added) poll(); } catch {} }
  async function genQueue() { setGenerating(true); try { const d = await api(`/party/${code}/generate-queue`, { method: 'POST' }); if (d.queue) setQueue(d.queue); if (d.members) setMembers(d.members); if (d.ai_summary) setSummary(d.ai_summary); } catch { alert('Add guests first'); } setGenerating(false); }
  async function vote(tid: string, v: number) { try { const d = await api(`/party/${code}/vote`, { method: 'POST', body: JSON.stringify({ track_id: tid, value: v }) }); if (d.queue) setQueue(d.queue); } catch {} }

  const displayQ = sortBy === 'votes' ? [...queue].sort((a, b) => b.votes - a.votes) : queue;
  const totalVotes = queue.reduce((s, q) => s + Math.abs(q.votes), 0);
  const nextTrack = playingIdx.current >= 0 && playingIdx.current < queue.length - 1 ? queue[playingIdx.current + 1] : null;
  const prevTrack = playingIdx.current > 0 ? queue[playingIdx.current - 1] : null;

  return (
    <div className="container">
      <div className="page-header">
        <h1>Host</h1><span className="code">{code}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {!hasSpotify && <a href={`${apiBase()}/auth/spotify/login?party_code=${code}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: '#1DB954', color: '#fff', borderRadius: 20, fontSize: 13, fontWeight: 700, textDecoration: 'none' }}>Connect Spotify</a>}
          {hasSpotify && <span style={{ padding: '6px 12px', background: 'var(--gnd)', color: 'var(--gn)', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>Spotify {sdkReady ? 'Ready' : 'Connected'}</span>}
          <button className="btn btn-sm btn-secondary" onClick={() => { navigator.clipboard.writeText(`${window.location.origin}/party/${code}`); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>{copied ? 'Copied!' : 'Share Link'}</button>
          <button className="btn btn-sm btn-primary" onClick={genQueue} disabled={generating || members.length === 0}>{generating ? 'Generating...' : 'Generate Queue'}</button>
        </div>
      </div>

      <div className="card"><div className="card-title">Listeners ({members.length})</div>
        {members.length === 0 ? <p style={{ color: 'var(--tx3)', fontSize: 13 }}>Share code <strong>{code}</strong></p> :
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>{members.map((m: any) => (<span key={m.id} className="user-chip active">{m.display_name}{m.genre && <span className="tag" style={{ marginLeft: 4 }}>{m.genre}</span>}</span>))}</div>}
      </div>

      <div className="card" ref={dropRef} style={{ position: 'relative' }}><div className="card-title">Search {src === 'spotify' && <span className="tag green">Spotify</span>}{src.includes('youtube') && <span className="tag" style={{ background: 'rgba(255,0,0,0.1)', color: '#f44', marginLeft: 4 }}>YouTube</span>}</div>
        <input className="input" placeholder="Search any song or artist..." value={sq} onChange={e => onSearch(e.target.value)} onFocus={() => results.length > 0 && setShowDrop(true)} />
        {showDrop && results.length > 0 && (<div className="search-drop">{results.map((t: any) => (
          <div key={t.id} className="search-item">
            {t.album_art ? <img src={t.album_art} alt="" /> : <div className="placeholder">&#9835;</div>}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</div>
              <div style={{ fontSize: 12, color: 'var(--tx2)' }}>{t.artist} {t.youtube_id && <span style={{ color: '#f44', fontWeight: 700 }}> YT</span>}</div>
            </div>
            <button className="btn btn-sm btn-primary" onClick={() => addTrack(t)} disabled={added.has(t.id)} style={{ padding: '4px 12px' }}>{added.has(t.id) ? '✓' : '+ Add'}</button>
            <button className="btn btn-sm btn-secondary" onClick={() => { addTrack(t); queueNext(t); }} style={{ padding: '4px 8px', fontSize: 11 }}>Next</button>
          </div>))}</div>)}
      </div>

      {summary && <div className="summary-box">{summary}</div>}

      {queue.length > 0 && (<>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          <div className="card-title" style={{ margin: 0 }}>Queue ({queue.length}) · {totalVotes} votes</div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button className="btn btn-sm btn-secondary" onClick={shuffleQueue} style={{ color: shuffled ? 'var(--ac)' : 'var(--tx2)' }}>Shuffle</button>
            <button className="btn btn-sm" onClick={() => setSortBy('score')} style={{ borderRadius: '8px 0 0 8px', background: sortBy === 'score' ? 'var(--ac)' : 'var(--bg3)', color: sortBy === 'score' ? '#fff' : 'var(--tx2)', border: '1px solid var(--bdr)' }}>Score</button>
            <button className="btn btn-sm" onClick={() => setSortBy('votes')} style={{ borderRadius: '0 8px 8px 0', background: sortBy === 'votes' ? 'var(--ac)' : 'var(--bg3)', color: sortBy === 'votes' ? '#fff' : 'var(--tx2)', border: '1px solid var(--bdr)', borderLeft: 'none' }}>Votes</button>
          </div>
        </div>
        <div className="card" style={{ padding: '8px 0' }}>{displayQ.map((item: any, idx: number) => {
          const isPlaying = item.track_id === np.track_id;
          const isYT = item.track_id?.startsWith('yt-');
          const canPlay = !!(item.uri || isYT);
          const isUA = (item.reasons || []).some((r: string) => r.startsWith('added by') || r.startsWith('queued by'));
          const isNext = nextTrack && nextTrack.track_id === item.track_id;
          return (
            <div key={item.track_id} className="track-row" style={isPlaying ? { background: 'var(--acd)' } : isUA ? { background: 'rgba(124,92,252,0.05)' } : {}}>
              <span className="track-rank" style={isPlaying ? { color: 'var(--gn)' } : {}}>{isPlaying ? '▶' : idx + 1}</span>
              <div className="track-info">
                <div className="track-name">{item.name}</div>
                <div className="track-artist">{item.artist}</div>
                <div className="track-meta">
                  {(item.genres || []).slice(0, 2).map((g: string) => <span key={g} className="tag">{g}</span>)}
                  {(item.matched_users || []).length > 0 && <span className="tag green">{item.matched_users.length}/{members.length}</span>}
                  {(item.reasons || []).filter((r: string) => r.startsWith('added by') || r.startsWith('queued by')).map((r: string) => <span key={r} className="tag accent">{r}</span>)}
                  {isPlaying && <span className="tag green">playing</span>}
                  {isNext && <span className="tag" style={{ background: 'rgba(96,165,250,0.15)', color: 'var(--bl)' }}>up next</span>}
                  {isYT && <span className="tag" style={{ background: 'rgba(255,0,0,0.1)', color: '#f44' }}>YT</span>}
                </div>
              </div>
              {canPlay && <button className="btn btn-sm btn-secondary" onClick={() => playTrack(item)} style={{ padding: '4px 10px', fontSize: 14 }}>▶</button>}
              <span className="track-score">{item.score?.toFixed(3)}</span>
              <div className="track-votes">
                <button className="btn-vote up" onClick={() => vote(item.track_id, 1)}>▲</button>
                <span className={`vote-count ${item.votes > 0 ? 'positive' : item.votes < 0 ? 'negative' : 'zero'}`} style={{ fontSize: 16, fontWeight: 800 }}>{item.votes > 0 ? `+${item.votes}` : item.votes}</span>
                <button className="btn-vote down" onClick={() => vote(item.track_id, -1)}>▼</button>
              </div>
            </div>);
        })}</div>
      </>)}

      {queue.length === 0 && <div className="card" style={{ textAlign: 'center', padding: 44, color: 'var(--tx2)' }}><p>Share code <strong>{code}</strong>, then <strong>Generate Queue</strong></p></div>}

      {np.youtube_id && (
        ytVideoId ? (
          <div style={{ position: 'fixed', bottom: 80, left: 0, right: 0, zIndex: 150, display: 'flex', justifyContent: 'center', padding: '0 16px' }}>
            <div style={{ background: 'var(--bg2)', border: '1px solid var(--bdr)', borderRadius: 12, overflow: 'hidden', width: '100%', maxWidth: 500, boxShadow: '0 -8px 32px rgba(0,0,0,0.5)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 12px' }}>
                <span style={{ fontSize: 12, color: 'var(--tx2)' }}>YouTube Player</span>
                <button onClick={() => setYtMinimized(true)} style={{ background: 'none', border: 'none', color: 'var(--tx3)', fontSize: 16, cursor: 'pointer' }}>_</button>
              <button onClick={() => { setYtVideoId(''); setYtMinimized(false); }} style={{ background: 'none', border: 'none', color: 'var(--tx3)', fontSize: 16, cursor: 'pointer', marginLeft: 8 }}>x</button>
              </div>
              <iframe width="100%" height={ytMinimized ? "0" : "220"} src={ytSrc} allow="autoplay; encrypted-media" allowFullScreen style={{ border: 'none', display: 'block' }} />
            </div>
          </div>
        ) : null
      )}

      {np.is_playing && np.name && !npExpanded && (
        <div className="now-playing" style={{ cursor: 'pointer' }} onClick={() => setNpExpanded(true)}>
          {np.album_art && <img src={np.album_art} alt="" />}
          <div className="np-info"><div className="np-name">{np.name}</div><div className="np-artist">{np.artist}</div>{nextTrack && <div style={{ fontSize: 10, color: 'var(--tx3)', marginTop: 2 }}>Up next: {nextTrack.name}</div>}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }} onClick={e => e.stopPropagation()}>
            <button onClick={playPrev} style={{ background: 'none', border: 'none', color: prevTrack ? 'var(--tx)' : 'var(--tx3)', fontSize: 18, cursor: 'pointer', padding: 4 }}>⏮</button>
            <button onClick={togglePlay} style={{ background: 'none', border: 'none', color: 'var(--tx)', fontSize: 22, cursor: 'pointer', padding: 4 }}>{np.is_playing ? '⏸' : '▶'}</button>
            <button onClick={playNext} style={{ background: 'none', border: 'none', color: nextTrack ? 'var(--tx)' : 'var(--tx3)', fontSize: 18, cursor: 'pointer', padding: 4 }}>⏭</button>
          </div>
          <span className="np-badge">PLAYING</span>
            {np.youtube_id && !ytVideoId && <button onClick={(e) => { e.stopPropagation(); setYtVideoId(np.youtube_id); }} style={{ background: 'rgba(255,0,0,0.15)', border: '1px solid rgba(255,0,0,0.3)', color: '#f44', fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer' }}>Watch Video</button>}
        </div>
      )}

      {np.is_playing && np.name && npExpanded && (
        <div style={{ position: 'fixed', inset: 0, background: 'linear-gradient(180deg, var(--bg) 0%, #1a1040 100%)', zIndex: 200, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 32 }}>
          {np.album_art && <img src={np.album_art} alt="" style={{ width: 280, height: 280, borderRadius: 16, boxShadow: '0 24px 80px rgba(124,92,252,0.3)', marginBottom: 28 }} />}
          <div style={{ fontSize: 24, fontWeight: 700, textAlign: 'center', marginBottom: 6 }}>{np.name}</div>
          <div style={{ fontSize: 16, color: 'var(--tx2)', marginBottom: 20 }}>{np.artist}</div>
          <div style={{ width: '100%', maxWidth: 340, marginBottom: 20 }}>
            <input type="range" min={0} max={duration || 1} value={position} onMouseDown={() => setSeeking(true)} onMouseUp={(e) => { setSeeking(false); seekTo(Number((e.target as any).value)); }} onTouchStart={() => setSeeking(true)} onTouchEnd={() => { setSeeking(false); seekTo(position); }} onChange={(e) => setPosition(Number(e.target.value))} style={{ width: '100%', accentColor: 'var(--ac)', cursor: 'pointer' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--tx3)' }}><span>{fmt(position)}</span><span>{fmt(duration)}</span></div>
          </div>
          <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
            <button onClick={shuffleQueue} style={{ background: 'none', border: 'none', color: shuffled ? 'var(--ac)' : 'var(--tx3)', fontSize: 22, cursor: 'pointer' }}>&#x1F500;</button>
            <button onClick={playPrev} style={{ background: 'none', border: 'none', color: prevTrack ? 'var(--tx)' : 'var(--tx3)', fontSize: 30, cursor: 'pointer' }}>⏮</button>
            <button onClick={togglePlay} style={{ width: 64, height: 64, borderRadius: '50%', background: 'var(--ac)', border: 'none', color: '#fff', fontSize: 28, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{np.is_playing ? '⏸' : '▶'}</button>
            <button onClick={playNext} style={{ background: 'none', border: 'none', color: nextTrack ? 'var(--tx)' : 'var(--tx3)', fontSize: 30, cursor: 'pointer' }}>⏭</button>
            <button onClick={() => setRepeatOn(!repeatOn)} style={{ background: 'none', border: 'none', color: repeatOn ? 'var(--ac)' : 'var(--tx3)', fontSize: 22, cursor: 'pointer' }}>&#x1F501;</button>
          </div>
          {prevTrack && <div style={{ marginTop: 16, fontSize: 12, color: 'var(--tx3)' }}>Previous: {prevTrack.name}</div>}
          {nextTrack && <div style={{ marginTop: 4, fontSize: 13, color: 'var(--bl)' }}>Up next: {nextTrack.name} — {nextTrack.artist}</div>}
          <button onClick={() => setNpExpanded(false)} style={{ marginTop: 28, background: 'none', border: 'none', color: 'var(--tx3)', fontSize: 13, cursor: 'pointer' }}>Close</button>
        </div>
      )}
    </div>
  );
}
