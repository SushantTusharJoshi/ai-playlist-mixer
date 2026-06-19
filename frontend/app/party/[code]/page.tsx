'use client';
import { use, useEffect, useState, useCallback, useRef } from 'react';
import { api } from '../../../lib/api';

export default function PartyPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [genres, setGenres] = useState<string[]>([]);
  const [members, setMembers] = useState<any[]>([]);
  const [queue, setQueue] = useState<any[]>([]);
  const [summary, setSummary] = useState('');
  const [np, setNp] = useState<any>({ is_playing: false });
  const [userId, setUserId] = useState('');
  const [userName, setUserName] = useState('');
  const [selGenre, setSelGenre] = useState('');
  const [joining, setJoining] = useState(false);
  const [voted, setVoted] = useState<Record<string, number>>({});
  const [sq, setSq] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [showDrop, setShowDrop] = useState(false);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [src, setSrc] = useState('');
  const timer = useRef<any>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    try {
      const d = await api(`/party/${code}/poll`);
      setMembers(d.members || []);
      if (d.queue?.length) setQueue(d.queue);
      setSummary(d.ai_summary || '');
      setNp(d.now_playing || { is_playing: false });
    } catch {}
  }, [code]);

  useEffect(() => { api('/genres').then(d => setGenres(d.genres)).catch(() => {}); poll(); const i = setInterval(poll, 3000); return () => clearInterval(i); }, [poll]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false); };
    document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h);
  }, []);

  async function joinParty() {
    if (!userName.trim() || !selGenre) return;
    setJoining(true);
    try {
      const d = await api(`/party/${code}/join`, { method: 'POST', body: JSON.stringify({ display_name: userName.trim(), genre: selGenre }) });
      setUserId(d.user_id);
      poll();
    } catch (e: any) { alert(e.message); }
    setJoining(false);
  }

  async function vote(tid: string, v: number) {
    if (voted[tid] === v) return;
    try {
      const d = await api(`/party/${code}/vote`, { method: 'POST', body: JSON.stringify({ track_id: tid, value: v }) });
      setVoted(p => ({ ...p, [tid]: v }));
      if (d.queue) setQueue(d.queue);
    } catch {}
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
    const name = userName.trim() || 'Guest';
    try {
      const d = await api(`/party/${code}/add-track?added_by=${encodeURIComponent(name)}`, { method: 'POST', body: JSON.stringify({
        id: t.id, name: t.name, artist: t.artist, genres: t.genres || [],
        energy: t.energy || 0.5, danceability: t.danceability || 0.5, popularity: t.popularity || 0.5,
        uri: t.uri || null, album_art: t.album_art || null
      }) });
      if (d.added) { setAdded(p => new Set(p).add(t.id)); poll(); }
    } catch {}
  }

  // Join screen
  if (!userId) {
    return (
      <div className="container">
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 50 }}>
          <h1 style={{ fontSize: 26, marginBottom: 4 }}>Join Party</h1>
          <span className="code" style={{ fontSize: 16, marginBottom: 28 }}>{code}</span>
          <p style={{ color: 'var(--tx2)', marginBottom: 8, fontSize: 13 }}>{members.length} already here</p>
          <input className="input" placeholder="Your name" value={userName}
            onChange={e => setUserName(e.target.value)}
            style={{ maxWidth: 300, marginBottom: 18, textAlign: 'center', fontSize: 15 }}
            onKeyDown={e => e.key === 'Enter' && selGenre && joinParty()} />
          <p style={{ color: 'var(--tx2)', fontSize: 12, marginBottom: 10 }}>Pick your vibe</p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center', maxWidth: 460 }}>
            {genres.map(g => (
              <button key={g} className={`user-chip ${selGenre === g ? 'active' : ''}`}
                onClick={() => setSelGenre(g)}>{g}</button>
            ))}
          </div>
          <button className="btn btn-primary" onClick={joinParty}
            disabled={!userName.trim() || !selGenre || joining}
            style={{ marginTop: 24, padding: '12px 36px', fontSize: 15, borderRadius: 24 }}>
            {joining ? 'Joining...' : 'Join the Party'}
          </button>
        </div>
      </div>
    );
  }

  // Party view
  return (
    <div className="container">
      <div className="page-header">
        <h1>Party</h1>
        <span className="code">{code}</span>
        <span style={{ fontSize: 12, color: 'var(--tx2)', marginLeft: 'auto' }}>{members.length} listeners</span>
      </div>

      <div className="card">
        <div className="card-title">In the room</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {members.map((m: any) => (
            <span key={m.id} className={`user-chip ${m.id === userId ? 'active' : ''}`}>
              {m.display_name}
              <span className="tag" style={{ marginLeft: 4 }}>{m.genre}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Search */}
      <div className="card" ref={dropRef} style={{ position: 'relative' }}>
        <div className="card-title">
          Search Songs
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

      {summary && <div className="summary-box">{summary}</div>}

      {queue.length > 0 ? (
        <div className="card" style={{ padding: '8px 0' }}>
          <div className="card-title" style={{ padding: '0 14px' }}>Queue · {queue.length} tracks</div>
          {queue.map((item: any, idx: number) => (
            <div key={item.track_id} className="track-row"
              style={np.track_id === item.track_id ? { background: 'var(--acd)' } : {}}>
              <span className="track-rank">{np.track_id === item.track_id ? '▶' : idx + 1}</span>
              <div className="track-info">
                <div className="track-name">{item.name}</div>
                <div className="track-artist">{item.artist}</div>
                <div className="track-meta">
                  {(item.genres || []).slice(0, 2).map((g: string) => <span key={g} className="tag">{g}</span>)}
                  {(item.reasons || []).filter((r: string) => r.startsWith('added by')).map((r: string) => (
                    <span key={r} className="tag accent">{r}</span>
                  ))}
                </div>
              </div>
              <div className="track-votes">
                <button className={`btn-vote up ${voted[item.track_id] === 1 ? 'active' : ''}`}
                  onClick={() => vote(item.track_id, 1)}>▲</button>
                <span className={`vote-count ${item.votes > 0 ? 'positive' : item.votes < 0 ? 'negative' : 'zero'}`}>
                  {item.votes > 0 ? `+${item.votes}` : item.votes}
                </span>
                <button className={`btn-vote down ${voted[item.track_id] === -1 ? 'active' : ''}`}
                  onClick={() => vote(item.track_id, -1)}>▼</button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card" style={{ textAlign: 'center', padding: 36, color: 'var(--tx2)' }}>
          Waiting for the host to generate the queue...
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
        </div>
      )}
    </div>
  );
}
