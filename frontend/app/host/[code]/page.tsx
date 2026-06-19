'use client';
import { use, useEffect, useState, useCallback, useRef } from 'react';
import { api, apiBase } from '../../../lib/api';

declare global { interface Window { onSpotifyWebPlaybackSDKReady: () => void; Spotify: any; } }

export default function HostPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [members, setMembers] = useState<any[]>([]);
  const [queue, setQueue] = useState<any[]>([]);
  const [summary, setSummary] = useState('');
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [tab, setTab] = useState<'queue'|'leaderboard'>('queue');
  const [np, setNp] = useState<any>({is_playing:false});
  const [hasSpotify, setHasSpotify] = useState(false);
  const [sq, setSq] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [showDrop, setShowDrop] = useState(false);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [src, setSrc] = useState('');
  const timer = useRef<any>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const [player, setPlayer] = useState<any>(null);
  const [deviceId, setDeviceId] = useState('');
  const [spToken, setSpToken] = useState('');
  const [sdkReady, setSdkReady] = useState(false);

  const poll = useCallback(async () => {
    try {
      const d = await api(`/party/${code}/poll`);
      setMembers(d.members || []);
      if (d.queue?.length) setQueue(d.queue);
      setSummary(d.ai_summary || '');
      setNp(d.now_playing || { is_playing: false });
      setHasSpotify(d.has_spotify || false);
    } catch {}
  }, [code]);

  useEffect(() => { poll(); const i = setInterval(poll, 3000); return () => clearInterval(i); }, [poll]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false); };
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h);
  }, []);

  useEffect(() => {
    if (!hasSpotify || sdkReady) return;
    api(`/party/${code}/spotify-token`).then(d => {
      if (!d.token) return;
      setSpToken(d.token);
      if (document.getElementById('spotify-sdk')) return;
      const s = document.createElement('script');
      s.id = 'spotify-sdk'; s.src = 'https://sdk.scdn.co/spotify-player.js';
      document.head.appendChild(s);
      window.onSpotifyWebPlaybackSDKReady = () => {
        const p = new window.Spotify.Player({ name: 'AI Playlist Mixer', getOAuthToken: (cb: any) => cb(d.token), volume: 0.8 });
        p.addListener('ready', ({ device_id }: any) => { setDeviceId(device_id); setSdkReady(true); });
        p.addListener('not_ready', () => setSdkReady(false));
        p.connect();
        setPlayer(p);
      };
    }).catch(() => {});
  }, [hasSpotify, code, sdkReady]);

  async function playTrack(item: any) {
    if (!sdkReady || !spToken || !item.uri) return;
    try {
      await fetch(`https://api.spotify.com/v1/me/player/play?device_id=${deviceId}`, {
        method: 'PUT', headers: { 'Authorization': `Bearer ${spToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ uris: [item.uri] }),
      });
      await api(`/party/${code}/now-playing`, { method: 'POST', body: JSON.stringify({
        track_id: item.track_id, name: item.name, artist: item.artist, uri: item.uri, album_art: item.album_art, is_playing: true
      }) });
      setNp({ track_id: item.track_id, name: item.name, artist: item.artist, album_art: item.album_art, is_playing: true });
    } catch (e) { console.error('Play failed:', e); }
  }

  async function togglePlay() {
    if (!player) return;
    player.togglePlay();
    const playing = !np.is_playing;
    setNp((p: any) => ({ ...p, is_playing: playing }));
    if (!playing) api(`/party/${code}/stop-playing`, { method: 'POST' }).catch(() => {});
  }

  function onSearch(val: string) {
    setSq(val);
    if (timer.current) clearTimeout(timer.current);
    if (!val.trim()) { setResults([]); setShowDrop(false); return; }
    timer.current = setTimeout(async () => {
      try {
        const d = await api('/search', { method: 'POST', body: JSON.stringify({ query: val.trim(), limit: 10 }) });
        setResults(d.results || []); setSrc(d.source || ''); setShowDrop(true);
      } catch {}
    }, 300);
  }

  async function addTrack(t: any) {
    try {
      const d = await api(`/party/${code}/add-track?added_by=Host`, { method: 'POST', body: JSON.stringify({
        id: t.id, name: t.name, artist: t.artist, genres: t.genres || [],
        energy: t.energy || 0.5, danceability: t.danceability || 0.5, popularity: t.popularity || 0.5,
        uri: t.uri || null, album_art: t.album_art || null
      }) });
      if (d.added) { setAdded(p => new Set(p).add(t.id)); poll(); }
    } catch {}
  }

  async function genQueue() {
    setGenerating(true);
    try {
      const d = await api(`/party/${code}/generate-queue`, { method: 'POST' });
      if (d.queue) setQueue(d.queue);
      if (d.members) setMembers(d.members);
      if (d.ai_summary) setSummary(d.ai_summary);
    } catch { alert('Add guests first'); }
    setGenerating(false);
  }

  async function vote(tid: string, v: number) {
    try { const d = await api(`/party/${code}/vote`, { method: 'POST', body: JSON.stringify({ track_id: tid, value: v }) }); if (d.queue) setQueue(d.queue); } catch {}
  }

  const lb = [...queue].sort((a, b) => b.votes - a.votes).filter(q => q.votes !== 0);

  return (
    <div className="container">
      <div className="page-header">
        <h1>Host</h1>
        <span className="code">{code}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {!hasSpotify && (
            <a href={`${apiBase()}/auth/spotify/login?party_code=${code}`}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: '#1DB954', color: '#fff', borderRadius: 20, fontSize: 13, fontWeight: 700, textDecoration: 'none' }}>
              Connect Spotify
            </a>
          )}
          {hasSpotify && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '6px 12px', background: 'var(--gnd)', color: 'var(--gn)', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>
              Spotify {sdkReady ? 'Ready' : 'Connected'}
            </span>
          )}
          <button className="btn btn-sm btn-secondary" onClick={() => { navigator.clipboard.writeText(`${window.location.origin}/party/${code}`); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>
            {copied ? 'Copied!' : 'Share Link'}
          </button>
          <button className="btn btn-sm btn-primary" onClick={genQueue} disabled={generating || members.length === 0}>
            {generating ? 'Generating...' : 'Generate Queue'}
          </button>
        </div>
      </div>

      {/* Members */}
      <div className="card">
        <div className="card-title">Listeners ({members.length})</div>
        {members.length === 0 ? (
          <p style={{ color: 'var(--tx3)', fontSize: 13 }}>Share code <strong>{code}</strong> with guests</p>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {members.map((m: any) => (
              <span key={m.id} className="user-chip active">
                {m.display_name}
                <span className="tag" style={{ marginLeft: 4 }}>{m.genre}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Search */}
      <div className="card" ref={dropRef} style={{ position: 'relative' }}>
        <div className="card-title">
          Search
          {src === 'spotify' && <span className="tag green">Spotify</span>}
        </div>
        <input className="input" placeholder="Search any song or artist..." value={sq}
          onChange={e => onSearch(e.target.value)} onFocus={() => results.length > 0 && setShowDrop(true)} />
        {showDrop && results.length > 0 && (
          <div className="search-drop">
            {results.map((t: any) => (
              <div key={t.id} className="search-item">
                {t.album_art ? <img src={t.album_art} alt="" /> : <div className="placeholder">♪</div>}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--tx2)' }}>{t.artist}</div>
                </div>
                <button className="btn btn-sm btn-primary" onClick={() => addTrack(t)} disabled={added.has(t.id)}
                  style={{ padding: '4px 12px' }}>
                  {added.has(t.id) ? '✓' : '+'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* AI Summary */}
      {summary && <div className="summary-box">{summary}</div>}

      {/* Tabs */}
      {queue.length > 0 && (
        <div style={{ display: 'flex', gap: 0, marginBottom: 14 }}>
          {(['queue', 'leaderboard'] as const).map((t, i) => (
            <button key={t} className="btn btn-sm" onClick={() => setTab(t)} style={{
              borderRadius: i === 0 ? '8px 0 0 8px' : '0 8px 8px 0',
              background: tab === t ? 'var(--ac)' : 'var(--bg3)',
              color: tab === t ? '#fff' : 'var(--tx2)',
              border: '1px solid var(--bdr)', borderLeft: i > 0 ? 'none' : undefined,
            }}>
              {t === 'leaderboard' ? `Votes (${lb.length})` : `Queue (${queue.length})`}
            </button>
          ))}
        </div>
      )}

      {/* Queue */}
      {tab === 'queue' && queue.length > 0 && (
        <div className="card" style={{ padding: '8px 0' }}>
          {queue.map((item: any, idx: number) => (
            <div key={item.track_id} className="track-row"
              style={np.track_id === item.track_id ? { background: 'var(--acd)' } : {}}>
              <span className="track-rank">{np.track_id === item.track_id ? '▶' : idx + 1}</span>
              <div className="track-info">
                <div className="track-name">{item.name}</div>
                <div className="track-artist">{item.artist}</div>
                <div className="track-meta">
                  {(item.genres || []).slice(0, 2).map((g: string) => <span key={g} className="tag">{g}</span>)}
                  {(item.matched_users || []).length > 0 && (
                    <span className="tag green">{item.matched_users.length}/{members.length}</span>
                  )}
                  {(item.reasons || []).filter((r: string) => r.startsWith('added by')).map((r: string) => (
                    <span key={r} className="tag accent">{r}</span>
                  ))}
                </div>
              </div>
              {sdkReady && item.uri && (
                <button className="btn btn-sm btn-secondary" onClick={() => playTrack(item)}
                  style={{ padding: '4px 10px', fontSize: 14 }}>▶</button>
              )}
              <span className="track-score">{item.score?.toFixed(3)}</span>
              <div className="track-votes">
                <button className="btn-vote up" onClick={() => vote(item.track_id, 1)}>▲</button>
                <span className={`vote-count ${item.votes > 0 ? 'positive' : item.votes < 0 ? 'negative' : 'zero'}`}>
                  {item.votes > 0 ? `+${item.votes}` : item.votes}
                </span>
                <button className="btn-vote down" onClick={() => vote(item.track_id, -1)}>▼</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Leaderboard */}
      {tab === 'leaderboard' && (
        <div className="card">
          <div className="card-title">Most Upvoted</div>
          {lb.length === 0 ? (
            <p style={{ color: 'var(--tx3)', textAlign: 'center', padding: 20 }}>No votes yet</p>
          ) : lb.map((item: any, idx: number) => (
            <div key={item.track_id} className="track-row"
              style={idx === 0 ? { background: 'var(--acd)', borderRadius: 8 } : {}}>
              <span className="track-rank" style={idx === 0 ? { fontSize: 16 } : {}}>{idx === 0 ? '♛' : idx + 1}</span>
              <div className="track-info">
                <div className="track-name">{item.name}</div>
                <div className="track-artist">{item.artist}</div>
              </div>
              {sdkReady && item.uri && (
                <button className="btn btn-sm btn-secondary" onClick={() => playTrack(item)}
                  style={{ padding: '4px 10px', fontSize: 14 }}>▶</button>
              )}
              <span className={`vote-count ${item.votes > 0 ? 'positive' : 'negative'}`}
                style={{ fontSize: 20, fontWeight: 800 }}>
                {item.votes > 0 ? `+${item.votes}` : item.votes}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {queue.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: 44, color: 'var(--tx2)' }}>
          <p style={{ fontSize: 15 }}>Share code <strong>{code}</strong> with guests, then hit <strong>Generate Queue</strong></p>
        </div>
      )}

      {/* Now Playing Bar */}
      {np.is_playing && np.name && (
        <div className="now-playing">
          {np.album_art && <img src={np.album_art} alt="" />}
          <div className="np-info">
            <div className="np-name">{np.name}</div>
            <div className="np-artist">{np.artist}</div>
          </div>
          <span className="np-badge">PLAYING</span>
          <button className="btn btn-sm btn-secondary" onClick={togglePlay}
            style={{ fontSize: 16, padding: '6px 12px' }}>⏸</button>
        </div>
      )}
    </div>
  );
}
