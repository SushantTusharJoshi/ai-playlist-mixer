'use client';
// What it does: the one music player for host and guests. The server's now_playing is the
// source of truth; media loads only when its seq changes, never on a plain poll.
// Catch it: "Polls every 3 s, a track-end event and a Next tap all touch playback. Why does nothing stutter or double skip?"
// Card: docs/cards/player.md
import { useEffect, useImperativeHandle, useRef, useState } from 'react';
import type { Ref } from 'react';
import { api, hostHeaders } from '@/lib/api';
import {
  EMPTY_NP, createAdvanceGuard, fmt, isSpotifyTrackEnd, mergeNowPlaying, normalize, positionAt,
  refreshDelayMs, tokenIsFresh, youtubeIdOf,
} from '@/lib/player-state';
import type { NowPlaying, SpotifyStateLite } from '@/lib/player-state';

declare global {
  interface Window {
    onSpotifyWebPlaybackSDKReady?: () => void;
    onYouTubeIframeAPIReady?: () => void;
    Spotify?: any;
    YT?: any;
  }
}

// ── Script loaders: each script is added once per page, however often the player mounts ──
let ytApi: Promise<any> | null = null;
function loadYouTubeApi(): Promise<any> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!ytApi) {
    ytApi = new Promise((resolve, reject) => {
      const before = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => { before?.(); resolve(window.YT); };
      const s = document.createElement('script');
      s.src = 'https://www.youtube.com/iframe_api';
      s.async = true;
      s.onerror = () => { ytApi = null; reject(new Error('load')); };
      document.head.appendChild(s);
    });
  }
  return ytApi;
}

let spSdk: Promise<any> | null = null;
function loadSpotifySdk(): Promise<any> {
  if (window.Spotify?.Player) return Promise.resolve(window.Spotify);
  if (!spSdk) {
    spSdk = new Promise((resolve, reject) => {
      window.onSpotifyWebPlaybackSDKReady = () => resolve(window.Spotify);
      const s = document.createElement('script');
      s.src = 'https://sdk.scdn.co/spotify-player.js';
      s.async = true;
      s.onerror = () => { spSdk = null; reject(new Error('load')); };
      document.head.appendChild(s);
    });
  }
  return spSdk;
}

function errorText(e: any): string {
  try { const d = JSON.parse(e?.message || ''); if (d?.detail) return String(d.detail); } catch {}
  return 'Could not reach the server';
}

const YT_ERRORS: Record<number, string> = {
  2: 'This YouTube video id is not valid',
  5: 'This video cannot play in the browser player',
  100: 'This video was removed or is private',
  101: 'The owner does not allow this video to play outside YouTube',
  150: 'The owner does not allow this video to play outside YouTube',
};

type Status = 'idle' | 'loading' | 'playing' | 'paused' | 'blocked' | 'error';

export type PlayerHandle = { play: (trackId: string) => void };

type Props = {
  code: string;
  canControl: boolean;          // host page on the device that holds the host key
  incoming: any;                // now_playing from the latest poll
  hasSpotify: boolean;
  hasQueue: boolean;
  upNextName?: string | null;
  prevName?: string | null;
  onNowPlaying?: (np: NowPlaying) => void;
  ref?: Ref<PlayerHandle>;
};

export default function Player({ code, canControl, incoming, hasSpotify, hasQueue, upNextName, prevName, onNowPlaying, ref }: Props) {
  const [np, setNp] = useState<NowPlaying>(EMPTY_NP);
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState('');
  const [armed, setArmed] = useState(false);       // host: pressed a control in this tab; guest: chose Watch here
  const [sdkReady, setSdkReady] = useState(false);
  const [repeat, setRepeat] = useState(false);
  const [shuffle, setShuffle] = useState(false);
  const [bigVideo, setBigVideo] = useState(true);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState<number | null>(null);
  const [, setTick] = useState(0);

  const npRef = useRef<NowPlaying>(EMPTY_NP);
  const armedRef = useRef(false);
  const optsRef = useRef({ repeat: false, shuffle: false, canControl, code });
  optsRef.current = { repeat, shuffle, canControl, code };

  const loadedSeq = useRef(-1);
  const loadedAt = useRef(0);
  const reportedDurationSeq = useRef(-1);
  const guard = useRef(createAdvanceGuard());

  const ytBox = useRef<HTMLDivElement>(null);
  const yt = useRef<any>(null);
  const ytReady = useRef<Promise<void> | null>(null);

  const sp = useRef<any>(null);
  const deviceId = useRef('');
  const spLast = useRef<SpotifyStateLite | null>(null);
  const spLastAt = useRef(0);
  const token = useRef({ token: '', expiresAt: 0 });
  const refreshing = useRef<Promise<string> | null>(null);
  const refreshTimer = useRef<any>(null);

  // ── State: merge every server copy through one function ──
  function adopt(raw: any) {
    if (!raw) return;
    const merged = mergeNowPlaying(npRef.current, normalize(raw));
    if (merged !== npRef.current) { npRef.current = merged; setNp(merged); }
  }
  useEffect(() => { adopt(incoming); }, [incoming]);
  useEffect(() => { onNowPlaying?.(np); }, [np, onNowPlaying]);

  function fail(msg: string) { setStatus('error'); setMessage(msg); }

  async function control(path: string, body: object): Promise<any> {
    setBusy(true);
    try {
      const d = await api(`/party/${code}/${path}`, { method: 'POST', headers: hostHeaders(code), body: JSON.stringify(body) });
      adopt(d.now_playing);
      return d;
    } catch (e) {
      fail(errorText(e));
      return null;
    } finally {
      setBusy(false);
    }
  }

  // ── Engines ──
  function enginePosition(): { pos: number; dur: number } | null {
    const cur = npRef.current;
    if (loadedSeq.current !== cur.seq) return null;
    if (cur.source === 'youtube' && yt.current?.getCurrentTime) {
      const num = (v: any) => (Number.isFinite(Number(v)) ? Number(v) * 1000 : 0);  // NaN before the video loads
      return { pos: num(yt.current.getCurrentTime()), dur: num(yt.current.getDuration?.()) };
    }
    if (cur.source === 'spotify' && spLast.current) {
      const s = spLast.current;
      const pos = s.paused ? s.position : s.position + (Date.now() - spLastAt.current);
      return { pos: s.duration ? Math.min(pos, s.duration) : pos, dur: s.duration };
    }
    return null;
  }

  function engineIsPlaying(): boolean {
    const cur = npRef.current;
    if (cur.source === 'youtube' && yt.current?.getPlayerState) return [1, 3].includes(yt.current.getPlayerState());
    if (cur.source === 'spotify' && spLast.current) return !spLast.current.paused;
    return cur.is_playing;
  }

  function pauseYouTube() { try { yt.current?.pauseVideo?.(); } catch {} }
  function pauseSpotify() { try { if (spLast.current && !spLast.current.paused) sp.current?.pause?.(); } catch {} }

  async function ensureYouTube(): Promise<void> {
    if (ytReady.current) return ytReady.current;
    const YT = await loadYouTubeApi();
    if (ytReady.current) return ytReady.current;
    const el = document.createElement('div');  // YT replaces this node with its iframe; React never owns it
    ytBox.current!.appendChild(el);
    ytReady.current = new Promise<void>((resolve) => {
      yt.current = new YT.Player(el, {
        width: '100%', height: '100%',
        playerVars: { autoplay: 1, rel: 0, playsinline: 1, modestbranding: 1 },
        events: {
          onReady: () => resolve(),
          onStateChange: (e: any) => handlers.current.onYtState(e.data),
          onError: (e: any) => handlers.current.onYtError(e.data),
        },
      });
    });
    return ytReady.current;
  }

  // ── Spotify token: refreshed 5 minutes before expiry, on SDK request, and after a 401 ──
  function scheduleRefresh() {
    clearTimeout(refreshTimer.current);
    const delay = refreshDelayMs(token.current.expiresAt, Date.now());
    refreshTimer.current = setTimeout(() => { refreshToken(); }, delay);
  }

  function refreshToken(): Promise<string> {
    if (refreshing.current) return refreshing.current;
    refreshing.current = (async () => {
      try {
        const d = await api(`/party/${code}/refresh-token`, { method: 'POST', headers: hostHeaders(code) });
        token.current = { token: d.token, expiresAt: d.expires_at || Date.now() / 1000 + 3600 };
        scheduleRefresh();
        return d.token as string;
      } catch (e) {
        fail(errorText(e));
        return token.current.token;
      } finally {
        refreshing.current = null;
      }
    })();
    return refreshing.current;
  }

  async function getToken(force = false): Promise<string> {
    if (!force && tokenIsFresh(token.current.expiresAt, Date.now())) return token.current.token;
    return refreshToken();
  }

  async function spotifyPlay(uri: string, positionMs: number, retry = true): Promise<boolean> {
    const t = await getToken();
    const r = await fetch(`https://api.spotify.com/v1/me/player/play?device_id=${encodeURIComponent(deviceId.current)}`, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ uris: [uri], position_ms: Math.max(0, Math.round(positionMs)) }),
    }).catch(() => null);
    if (!r) { fail('Network error talking to Spotify'); return false; }
    if (r.ok) return true;
    if (r.status === 401 && retry) { await getToken(true); return spotifyPlay(uri, positionMs, false); }
    if (r.status === 403) fail('Spotify refused playback: the host account needs Premium');
    else if (r.status === 404) fail('Spotify lost this browser as a player: reload the page');
    else if (r.status === 429) fail('Spotify is rate limiting: try again in a moment');
    else fail(`Spotify error ${r.status}`);
    return false;
  }

  useEffect(() => {
    if (!canControl || !hasSpotify) return;
    let cancelled = false;
    let player: any = null;
    (async () => {
      try {
        const d = await api(`/party/${code}/spotify-token`, { headers: hostHeaders(code) });
        if (!d.token || cancelled) return;
        token.current = { token: d.token, expiresAt: d.expires_at || 0 };
        if (tokenIsFresh(token.current.expiresAt, Date.now())) scheduleRefresh(); else await refreshToken();
      } catch { return; }
      const Spotify = await loadSpotifySdk().catch(() => null);
      if (cancelled) return;
      if (!Spotify) { fail('The Spotify player script did not load'); return; }
      player = new Spotify.Player({
        name: 'AI Playlist Mixer', volume: 0.8,
        getOAuthToken: (cb: (t: string) => void) => { getToken().then(t => t && cb(t)); },
      });
      player.addListener('ready', ({ device_id }: any) => { deviceId.current = device_id; setSdkReady(true); });
      player.addListener('not_ready', () => { deviceId.current = ''; setSdkReady(false); });
      player.addListener('initialization_error', () => fail('This browser cannot run the Spotify player'));
      player.addListener('authentication_error', () => { refreshToken(); fail('Spotify sign-in failed: connect Spotify again'); });
      player.addListener('account_error', () => fail('Spotify playback needs a Premium account'));
      player.addListener('playback_error', () => fail('Spotify could not play this track'));
      player.addListener('player_state_changed', (s: any) => handlers.current.onSpState(s));
      sp.current = player;
      player.connect();
    })();
    return () => {
      cancelled = true;
      clearTimeout(refreshTimer.current);
      player?.disconnect?.();
      sp.current = null; deviceId.current = ''; spLast.current = null;
      setSdkReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canControl, hasSpotify, code]);

  // ── Load the current track into the right engine (once per seq) ──
  async function loadMedia(cur: NowPlaying, forcePlay = false) {
    loadedSeq.current = cur.seq;
    loadedAt.current = Date.now();
    spLast.current = null;
    setMessage('');
    if (!cur.track_id || cur.ended) {
      pauseYouTube(); pauseSpotify();
      setStatus('idle');
      return;
    }
    const startMs = positionAt(cur, Date.now());
    const shouldPlay = cur.is_playing || forcePlay;
    if (cur.source === 'youtube') {
      pauseSpotify();
      const vid = youtubeIdOf(cur);
      if (!vid) { fail('No video for this track'); return; }
      setStatus('loading');
      try { await ensureYouTube(); } catch { fail('The YouTube player did not load'); return; }
      if (loadedSeq.current !== cur.seq) return;  // a newer track arrived while the script loaded
      const args = { videoId: vid, startSeconds: Math.floor(startMs / 1000) };
      if (shouldPlay) yt.current.loadVideoById(args); else yt.current.cueVideoById(args);
      setTimeout(() => {
        if (loadedSeq.current !== cur.seq || !shouldPlay) return;
        const st = yt.current?.getPlayerState?.();
        if (st !== 1 && st !== 3 && st !== 0) { setStatus('blocked'); setMessage('The browser held back autoplay: press play'); }
      }, 4000);
    } else if (cur.source === 'spotify') {
      pauseYouTube();
      if (!optsRef.current.canControl) { setStatus('idle'); return; }  // guests do not play Spotify
      if (!deviceId.current) {
        loadedSeq.current = -1;  // try again when the SDK reports ready
        setStatus('loading');
        setMessage(hasSpotify ? 'Starting the Spotify player...' : 'Connect Spotify to play this track');
        return;
      }
      setStatus('loading');
      const ok = await spotifyPlay(cur.uri || '', startMs);
      if (ok && !shouldPlay) { try { await sp.current?.pause(); } catch {} }
    } else {
      fail('This track has no playable source on this device');
    }
  }

  useEffect(() => {
    if (!armedRef.current || loadedSeq.current === np.seq) return;
    loadMedia(np);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [np.seq, sdkReady, armed]);

  // Guests watching YouTube follow the host's pause, resume and seek.
  useEffect(() => {
    if (canControl || !armedRef.current || np.source !== 'youtube' || loadedSeq.current !== np.seq || !yt.current?.getPlayerState) return;
    if (np.is_playing) {
      const e = enginePosition();
      const want = positionAt(np, Date.now());
      if (e && Math.abs(e.pos - want) > 4000) yt.current.seekTo(want / 1000, true);
      yt.current.playVideo();
    } else {
      yt.current.pauseVideo();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [np.is_playing, np.updated_at]);

  // ── Reports to the server (host only) ──
  async function report(isPlaying: boolean, positionMs?: number) {
    const cur = npRef.current;
    if (!optsRef.current.canControl || !cur.track_id) return;
    const e = enginePosition();
    const pos = positionMs ?? e?.pos ?? positionAt(cur, Date.now());
    const dur = e?.dur || cur.duration_ms || 0;
    if (dur) reportedDurationSeq.current = cur.seq;
    try {
      const d = await api(`/party/${code}/playback`, {
        method: 'POST', headers: hostHeaders(code),
        body: JSON.stringify({ seq: cur.seq, is_playing: isPlaying, position_ms: Math.round(pos), duration_ms: Math.round(dur) }),
      });
      adopt(d.now_playing);
    } catch {}
  }

  function advance(seq: number) {
    if (!optsRef.current.canControl || !guard.current.claim(seq)) return;
    const { repeat: r, shuffle: s } = optsRef.current;
    control('next', { expected_seq: seq, repeat: r, shuffle: s });
  }

  function onYtState(state: number) {
    const cur = npRef.current;
    if (cur.source !== 'youtube' || loadedSeq.current !== cur.seq) return;
    const settled = Date.now() - loadedAt.current > 1500;
    if (state === 1) {
      setStatus('playing'); setMessage('');
      if (optsRef.current.canControl && ((settled && !cur.is_playing) || reportedDurationSeq.current !== cur.seq)) report(true);
    } else if (state === 2) {
      setStatus('paused');
      if (optsRef.current.canControl && settled && cur.is_playing) report(false);  // paused inside the video frame
    } else if (state === 3) {
      setStatus('loading');
    } else if (state === 5) {
      setStatus('paused');
    } else if (state === 0) {
      setStatus('idle');
      advance(cur.seq);
    }
  }

  function onYtError(codeNum: number) {
    const cur = npRef.current;
    fail(YT_ERRORS[codeNum] || 'YouTube could not play this video');
    if (!optsRef.current.canControl) return;
    setMessage((YT_ERRORS[codeNum] || 'YouTube could not play this video') + '. Skipping in 3 s.');
    setTimeout(() => { if (npRef.current.seq === cur.seq) advance(cur.seq); }, 3000);
  }

  function onSpState(s: any) {
    if (!s) { spLast.current = null; return; }  // playback moved to another device
    const uris = (t: any) => [t?.uri, t?.linked_from?.uri].filter(Boolean);
    const lite: SpotifyStateLite = {
      paused: s.paused, position: s.position, duration: s.duration,
      previousUris: (s.track_window?.previous_tracks || []).flatMap(uris),
      currentUri: s.track_window?.current_track?.uri ?? null,
    };
    const prev = spLast.current;
    spLast.current = lite;
    spLastAt.current = Date.now();
    const cur = npRef.current;
    if (cur.source !== 'spotify' || loadedSeq.current !== cur.seq) return;
    const sinceLoad = Date.now() - loadedAt.current;
    if (sinceLoad > 2000 && isSpotifyTrackEnd(prev, lite, cur.uri)) { setStatus('idle'); advance(cur.seq); return; }
    setStatus(s.paused ? 'paused' : s.loading ? 'loading' : 'playing');
    if (!s.paused) setMessage('');
    if (sinceLoad > 1500 && s.paused === cur.is_playing) report(!s.paused);  // paused or resumed from another Spotify app
    else if (s.duration && reportedDurationSeq.current !== cur.seq) report(!s.paused);
  }

  // Engine callbacks are registered once; this ref always points at this render's functions.
  const handlers = useRef({ onYtState, onYtError, onSpState });
  handlers.current = { onYtState, onYtError, onSpState };

  // ── Controls ──
  function gesture() {
    armedRef.current = true;
    setArmed(true);
    try { sp.current?.activateElement?.(); } catch {}  // browsers only start audio from a user gesture
  }

  async function playTrack(trackId: string) {
    gesture();
    setStatus('loading'); setMessage('');
    await control('play', { track_id: trackId });
  }

  async function next() {
    gesture();
    await control('next', { expected_seq: npRef.current.seq, repeat, shuffle });
  }

  async function prev() {
    gesture();
    await control('prev', { expected_seq: npRef.current.seq });
  }

  async function togglePlay() {
    gesture();
    const cur = npRef.current;
    if (!cur.track_id) {
      if (hasQueue) await control('next', { expected_seq: cur.seq, repeat: true, shuffle });
      return;
    }
    if (loadedSeq.current !== cur.seq || status === 'blocked' || status === 'error') {
      await loadMedia(cur, true);  // first press in this tab: start here at the room's position
      if (canControl && !cur.is_playing) report(true, positionAt(cur, Date.now()));
      if (!canControl && cur.source === 'youtube') yt.current?.playVideo?.();
      return;
    }
    if (engineIsPlaying()) {
      if (cur.source === 'youtube') pauseYouTube(); else { try { await sp.current?.pause(); } catch {} }
      if (canControl) report(false);
    } else {
      if (cur.source === 'youtube') yt.current?.playVideo?.(); else { try { await sp.current?.resume(); } catch {} }
      if (canControl) report(true);
    }
  }

  async function seek(ms: number) {
    setDrag(null);
    const cur = npRef.current;
    if (!canControl || loadedSeq.current !== cur.seq) return;
    if (cur.source === 'youtube') yt.current?.seekTo?.(ms / 1000, true);
    else { try { await sp.current?.seek(ms); } catch {} }
    report(engineIsPlaying(), ms);
  }

  function watchHere() {
    gesture();
    loadedSeq.current = -1;
    loadMedia(npRef.current);
  }

  function stopWatching() {
    pauseYouTube();
    armedRef.current = false;
    setArmed(false);
    loadedSeq.current = -1;
    setStatus('idle');
  }

  const latestPlay = useRef(playTrack);
  latestPlay.current = playTrack;
  useImperativeHandle(ref, () => ({ play: (id: string) => { latestPlay.current(id); } }), []);

  // Re-render twice a second for the progress bar while something plays.
  useEffect(() => {
    if (!np.track_id) return;
    const i = setInterval(() => setTick(t => t + 1), 500);
    return () => clearInterval(i);
  }, [np.track_id]);

  useEffect(() => () => { try { yt.current?.destroy?.(); } catch {} }, []);

  // ── View ──
  const engine = enginePosition();
  const pos = drag ?? engine?.pos ?? positionAt(np, Date.now());
  const dur = engine?.dur || np.duration_ms;
  const loadedHere = armed && loadedSeq.current === np.seq;
  const playingNow = loadedHere ? status === 'playing' || status === 'loading' : np.is_playing;
  const showVideo = armed && np.source === 'youtube' && !!np.track_id;
  const visible = !!np.track_id || (canControl && (hasQueue || !!np.ended));

  let hint = '';
  if (message) hint = message;
  else if (np.ended) hint = canControl ? 'Queue finished. Press play to start over.' : 'Queue finished';
  else if (!np.track_id) hint = canControl ? 'Press play to start the queue' : '';
  else if (canControl && !loadedHere && np.track_id) hint = np.is_playing ? 'Press play to hear it on this device' : 'Paused';
  else if (!canControl && np.source === 'spotify') hint = 'Playing on the host speaker (Spotify)';
  else if (!canControl && !np.is_playing) hint = 'Paused by the host';
  else if (status === 'loading') hint = 'Loading...';
  else if (upNextName) hint = `Up next: ${upNextName}`;

  return (
    <>
      <div ref={ytBox} className={`player-video ${showVideo ? (bigVideo ? 'big' : 'small') : 'off'}`} aria-hidden={!showVideo} />
      {visible && (
        <div className="player" role="region" aria-label="Now playing">
          <div className="player-progress">
            <span>{fmt(pos)}</span>
            <input
              type="range" className="player-seek" aria-label="Seek"
              min={0} max={Math.max(dur, 1)} step={1000} value={Math.min(pos, Math.max(dur, 1))}
              disabled={!canControl || !loadedHere || !dur}
              onChange={e => setDrag(Number(e.target.value))}
              onPointerUp={e => seek(Number((e.target as HTMLInputElement).value))}
              onKeyUp={e => seek(Number((e.target as HTMLInputElement).value))}
            />
            <span>{fmt(dur)}</span>
          </div>
          <div className="player-row">
            <div className="player-art">
              {np.album_art ? <img src={np.album_art} alt="" /> : <span aria-hidden>&#9835;</span>}
            </div>
            <div className="player-info">
              <div className="player-title">{np.name || (np.ended ? 'Queue finished' : 'Nothing playing')}</div>
              <div className="player-sub">
                {np.artist && <span className="player-artist">{np.artist}</span>}
                {np.source === 'spotify' && <span className="player-badge spotify">Spotify</span>}
                {np.source === 'youtube' && <span className="player-badge youtube">YouTube</span>}
                {canControl && hasSpotify && <span className="player-badge muted">{sdkReady ? 'Spotify ready' : 'Spotify starting'}</span>}
              </div>
              {hint && <div className={`player-hint ${status === 'error' ? 'error' : ''}`} role={status === 'error' ? 'alert' : undefined}>{hint}</div>}
            </div>
            {canControl ? (
              <div className="player-controls">
                <button className="player-btn" onClick={prev} disabled={busy || !np.track_id} title={prevName ? `Previous: ${prevName}` : 'Restart track'} aria-label="Previous">
                  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><path fill="currentColor" d="M6 5h2v14H6zM20 5v14L9 12z" /></svg>
                </button>
                <button className="player-btn main" onClick={togglePlay} disabled={busy && !np.track_id} aria-label={playingNow && loadedHere ? 'Pause' : 'Play'}>
                  {playingNow && loadedHere
                    ? <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden><path fill="currentColor" d="M6 5h4v14H6zM14 5h4v14h-4z" /></svg>
                    : <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden><path fill="currentColor" d="M7 4v16l13-8z" /></svg>}
                </button>
                <button className="player-btn" onClick={next} disabled={busy || (!np.track_id && !hasQueue)} title={upNextName ? `Next: ${upNextName}` : 'Next'} aria-label="Next">
                  <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden><path fill="currentColor" d="M16 5h2v14h-2zM4 5v14l11-7z" /></svg>
                </button>
                <button className={`player-toggle ${repeat ? 'on' : ''}`} onClick={() => setRepeat(r => !r)} aria-pressed={repeat} title="Repeat the queue">Repeat</button>
                <button className={`player-toggle ${shuffle ? 'on' : ''}`} onClick={() => setShuffle(s => !s)} aria-pressed={shuffle} title="Pick the next track at random">Shuffle</button>
                {showVideo && <button className="player-toggle" onClick={() => setBigVideo(b => !b)}>{bigVideo ? 'Shrink video' : 'Show video'}</button>}
              </div>
            ) : (
              <div className="player-controls">
                {!np.is_playing && np.track_id && <span className="player-badge muted">Paused</span>}
                {np.source === 'youtube' && np.track_id && (armed
                  ? <button className="player-toggle" onClick={stopWatching}>Stop watching</button>
                  : <button className="player-toggle on" onClick={watchHere}>Watch here</button>)}
                {showVideo && <button className="player-toggle" onClick={() => setBigVideo(b => !b)}>{bigVideo ? 'Shrink video' : 'Show video'}</button>}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
