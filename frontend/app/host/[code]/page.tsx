'use client';
import { use, useEffect, useState, useCallback, useRef } from 'react';
import { api, hostHeaders, loadHostKey } from '@/lib/api';
import Player from '@/app/components/Player';
import type { PlayerHandle } from '@/app/components/Player';
import { playableAs } from '@/lib/player-state';
import type { NowPlaying } from '@/lib/player-state';

export default function HostPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [members, setMembers] = useState<any[]>([]);
  const [queue, setQueue] = useState<any[]>([]);
  const [summary, setSummary] = useState('');
  const [generating, setGenerating] = useState(false);
  const [copied, setCopied] = useState(false);
  const [hasSpotify, setHasSpotify] = useState(false);
  const [canResolve, setCanResolve] = useState(false);
  const [sq, setSq] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [showDrop, setShowDrop] = useState(false);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [src, setSrc] = useState('');
  const searchTimer = useRef<any>(null);
  const dropRef = useRef<HTMLDivElement>(null);
  const [cooldown, setCooldown] = useState(0);
  const [sortBy, setSortBy] = useState<'score' | 'votes'>('score');
  const [isHost, setIsHost] = useState<boolean | null>(null);  // null until localStorage is read
  // Playback lives in <Player>; the page only keeps what it needs to mark queue rows.
  const [incomingNp, setIncomingNp] = useState<any>(null);
  const [npId, setNpId] = useState('');
  const [upNextId, setUpNextId] = useState<string | null>(null);
  const [prevId, setPrevId] = useState<string | null>(null);
  const player = useRef<PlayerHandle>(null);
  const onNowPlaying = useCallback((np: NowPlaying) => setNpId(np.track_id), []);

  const poll = useCallback(async () => {
    try {
      const d = await api(`/party/${code}/poll`);
      setMembers(d.members || []);
      if (d.queue?.length) setQueue(d.queue);
      setSummary(d.ai_summary || '');
      setIncomingNp(d.now_playing || null);
      setUpNextId(d.up_next_track_id ?? null);
      setPrevId(d.prev_track_id ?? null);
      setHasSpotify(d.has_spotify || false);
      setCanResolve(!!d.can_resolve);
    } catch {}
  }, [code]);

  useEffect(() => { poll(); const i = setInterval(poll, 3000); return () => clearInterval(i); }, [poll]);
  useEffect(() => { setIsHost(!!loadHostKey(code)); }, [code]);
  useEffect(() => { const h = (e: MouseEvent) => { if (dropRef.current && !dropRef.current.contains(e.target as Node)) setShowDrop(false); }; document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h); }, []);

  function onSearch(val: string) { setSq(val); if (searchTimer.current) clearTimeout(searchTimer.current); if (!val.trim()) { setResults([]); setShowDrop(false); return; } searchTimer.current = setTimeout(async () => { try { const d = await api('/search', { method: 'POST', body: JSON.stringify({ query: val.trim(), limit: 10 }) }); setResults(d.results || []); setSrc(d.source || ''); setShowDrop(true); } catch {} }, 300); }

  function trackBody(t: any) { return JSON.stringify({ id: t.id, name: t.name, artist: t.artist, genres: t.genres || [], energy: t.energy || 0.5, danceability: t.danceability || 0.5, popularity: t.popularity || 0.5, uri: t.uri || null, album_art: t.album_art || null, youtube_id: t.youtube_id || null }); }
  async function addTrack(t: any) { try { const d = await api(`/party/${code}/add-track`, { method: 'POST', headers: hostHeaders(code), body: trackBody(t) }); if (d.added) { setAdded(p => new Set(p).add(t.id)); poll(); } } catch {} }
  // Only queue-next: calling add-track first raced it, so the track landed at the end as a duplicate.
  async function queueNext(t: any) { try { const d = await api(`/party/${code}/queue-next`, { method: 'POST', headers: hostHeaders(code), body: trackBody(t) }); if (d.added) { setAdded(p => new Set(p).add(t.id)); poll(); } } catch {} }
  async function connectSpotify() { try { const d = await api(`/party/${code}/spotify/login-url`, { method: 'POST', headers: hostHeaders(code) }); if (d.url) window.location.href = d.url; } catch { alert('Only the device that created this party can connect Spotify'); } }
  async function genQueue() { setGenerating(true); try { const d = await api(`/party/${code}/generate-queue`, { method: 'POST', headers: hostHeaders(code) }); if (d.queue) setQueue(d.queue); if (d.members) setMembers(d.members); if (d.ai_summary) setSummary(d.ai_summary); setCooldown(30); const t = setInterval(() => setCooldown(c => { if (c <= 1) { clearInterval(t); return 0; } return c - 1; }), 1000); } catch { alert('Add guests first'); } setGenerating(false); }
  async function vote(tid: string, v: number) { try { const d = await api(`/party/${code}/vote`, { method: 'POST', headers: hostHeaders(code), body: JSON.stringify({ track_id: tid, value: v }) }); if (d.queue) setQueue(d.queue); } catch {} }

  const displayQ = sortBy === 'votes' ? [...queue].sort((a, b) => b.votes - a.votes) : queue;
  const totalVotes = queue.reduce((s, q) => s + Math.abs(q.votes), 0);
  const nextTrack = upNextId ? queue.find(q => q.track_id === upNextId) : null;
  const prevTrack = prevId ? queue.find(q => q.track_id === prevId) : null;

  return (
    <div className="container">
      <div className="page-header">
        <h1>Host</h1><span className="code">{code}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          {isHost === false && <span style={{ fontSize: 12, color: 'var(--tx3)' }}>Host controls work only on the device that created this party</span>}
          {!hasSpotify && isHost && <button onClick={connectSpotify} style={{ border: 'none', cursor: 'pointer',  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: '#1DB954', color: '#fff', borderRadius: 20, fontSize: 13, fontWeight: 700, textDecoration: 'none' }}>Connect Spotify</button>}
          {hasSpotify && <span style={{ padding: '6px 12px', background: 'var(--gnd)', color: 'var(--gn)', borderRadius: 6, fontSize: 12, fontWeight: 600 }}>Spotify connected</span>}
          <button className="btn btn-sm btn-secondary" onClick={() => { navigator.clipboard.writeText(`${window.location.origin}/party/${code}`); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>{copied ? 'Copied!' : 'Share Link'}</button>
          <button className="btn btn-sm btn-primary" onClick={genQueue} disabled={generating || members.length === 0 || cooldown > 0}>{generating ? 'Generating...' : cooldown > 0 ? `Wait ${cooldown}s` : 'Generate Queue'}</button>
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
            <button className="btn btn-sm btn-secondary" onClick={() => queueNext(t)} disabled={added.has(t.id)} style={{ padding: '4px 8px', fontSize: 11 }}>Next</button>
          </div>))}</div>)}
      </div>

      {summary && <div className="summary-box">{summary}</div>}

      {queue.length > 0 && (<>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          <div className="card-title" style={{ margin: 0 }}>Queue ({queue.length}) · {totalVotes} votes</div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button className="btn btn-sm" onClick={() => setSortBy('score')} style={{ borderRadius: '8px 0 0 8px', background: sortBy === 'score' ? 'var(--ac)' : 'var(--bg3)', color: sortBy === 'score' ? '#fff' : 'var(--tx2)', border: '1px solid var(--bdr)' }}>Score</button>
            <button className="btn btn-sm" onClick={() => setSortBy('votes')} style={{ borderRadius: '0 8px 8px 0', background: sortBy === 'votes' ? 'var(--ac)' : 'var(--bg3)', color: sortBy === 'votes' ? '#fff' : 'var(--tx2)', border: '1px solid var(--bdr)', borderLeft: 'none' }}>Votes</button>
          </div>
        </div>
        <div className="card" style={{ padding: '8px 0' }}>{displayQ.map((item: any, idx: number) => {
          const isPlaying = item.track_id === npId;
          const isYT = !!item.youtube_id;
          const playAs = playableAs(item, hasSpotify, canResolve);
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
              {isHost && playAs && <button className="btn btn-sm btn-secondary" onClick={() => player.current?.play(item.track_id)} title={playAs === 'match' ? 'Find this track and play it' : 'Play now'} aria-label={`Play ${item.name}`} style={{ padding: '4px 10px', fontSize: 14 }}>▶</button>}
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

      <Player ref={player} code={code} canControl={!!isHost} incoming={incomingNp} hasSpotify={hasSpotify}
        hasQueue={queue.length > 0} upNextName={nextTrack?.name ?? null} prevName={prevTrack?.name ?? null}
        onNowPlaying={onNowPlaying} />
    </div>
  );
}
