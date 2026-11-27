// Player rules with no React and no browser APIs, so they run under `node --test`.
// The server's now_playing is the source of truth; these helpers decide when a
// poll may replace the local copy, where the progress bar is, when a track has
// ended, and when to refresh the Spotify token.

export type Source = 'spotify' | 'youtube' | '';

export interface NowPlaying {
  track_id: string;
  name: string;
  artist: string;
  uri?: string | null;
  album_art?: string | null;
  youtube_id?: string | null;
  is_playing: boolean;
  started_at?: number;
  seq: number;
  source: Source;
  position_ms: number;
  duration_ms: number;
  updated_at: number; // seconds since epoch, server clock
  ended?: boolean;
}

export interface QueueTrack {
  track_id: string;
  name: string;
  artist: string;
  uri?: string | null;
  album_art?: string | null;
  youtube_id?: string | null;
}

export const EMPTY_NP: NowPlaying = {
  track_id: '', name: '', artist: '', is_playing: false, seq: -1, source: '',
  position_ms: 0, duration_ms: 0, updated_at: 0,
};

/** Fill fields an older backend does not send, so the rest of the code can rely on them. */
export function normalize(raw: any): NowPlaying {
  if (!raw) return EMPTY_NP;
  return {
    ...EMPTY_NP,
    ...raw,
    seq: typeof raw.seq === 'number' ? raw.seq : 0,
    source: raw.source || (raw.youtube_id ? 'youtube' : raw.uri ? 'spotify' : ''),
    position_ms: raw.position_ms || 0,
    duration_ms: raw.duration_ms || 0,
    updated_at: raw.updated_at || raw.started_at || 0,
  };
}

/**
 * Decide whether an incoming copy (from a poll or a control reply) replaces the
 * local one. Returns the current object when nothing changed, so React skips the
 * render and the media players are left alone.
 * - A lower seq is an older track: a poll that left before a Next reply. Ignore it.
 * - Same seq: take it only if it is at least as new (pause and seek bump updated_at).
 */
export function mergeNowPlaying(current: NowPlaying, incoming: NowPlaying): NowPlaying {
  if (incoming.seq < current.seq) return current;
  if (incoming.seq === current.seq) {
    if (incoming.updated_at < current.updated_at) return current;
    if (incoming.updated_at === current.updated_at && incoming.is_playing === current.is_playing
      && incoming.position_ms === current.position_ms && incoming.duration_ms === current.duration_ms
      && incoming.track_id === current.track_id) return current;
  }
  return incoming;
}

/** Where the track is now, from the last reported position. Used by guests and before the engine reports. */
export function positionAt(np: NowPlaying, nowMs: number): number {
  if (!np.track_id) return 0;
  let pos = np.position_ms;
  if (np.is_playing && np.updated_at) pos += Math.max(0, nowMs - np.updated_at * 1000);
  if (np.duration_ms) pos = Math.min(pos, np.duration_ms);
  return Math.max(0, Math.round(pos));
}

const YT_ID = /^[A-Za-z0-9_-]{11}$/;

/** A real video id, or null. "yt-search-..." is the no-key search link, not a video. */
export function youtubeIdOf(t: { track_id: string; youtube_id?: string | null }): string | null {
  if (t.youtube_id && YT_ID.test(t.youtube_id)) return t.youtube_id;
  if (t.track_id.startsWith('yt-')) {
    const vid = t.track_id.slice(3);
    if (YT_ID.test(vid)) return vid;
  }
  return null;
}

/** How this host can play a queue row: a source, "match" (the server will find one), or null. */
export function playableAs(t: QueueTrack, hasSpotify: boolean, canResolve: boolean): Source | 'match' | null {
  if (t.uri && t.uri.startsWith('spotify:') && hasSpotify) return 'spotify';
  if (youtubeIdOf(t)) return 'youtube';
  // Catalog tracks, and Spotify results on a host without a Spotify login, are matched by the server.
  if (canResolve) return 'match';
  return null;
}

/**
 * One advance per track. The ended event, an error auto-skip and a tap can all
 * fire for the same track; only the first one for a given seq goes through.
 * (The server also checks expected_seq, so two tabs cannot double skip either.)
 */
export function createAdvanceGuard() {
  let lastSeq = -Infinity;
  return {
    claim(seq: number): boolean {
      if (seq <= lastSeq) return false;
      lastSeq = seq;
      return true;
    },
    get last() { return lastSeq; },
  };
}

export interface SpotifyStateLite {
  paused: boolean;
  position: number;
  duration: number;
  previousUris: string[];
  currentUri: string | null;
}

/**
 * The Web Playback SDK has no "ended" event. When a single-uri play finishes it
 * reports paused at position 0, and the finished track moves to previous_tracks
 * (or the last position we saw was within 3 s of the end).
 */
export function isSpotifyTrackEnd(prev: SpotifyStateLite | null, next: SpotifyStateLite, uri: string | null | undefined): boolean {
  if (!uri || !next.paused || next.position !== 0) return false;
  if (next.previousUris.includes(uri)) return true;
  if (prev && !prev.paused && prev.duration > 0 && prev.duration - prev.position < 3000) return true;
  return false;
}

/** Spotify access tokens last an hour. Refresh 5 minutes early, never sooner than 10 s from now. */
export function refreshDelayMs(expiresAtSec: number, nowMs: number, leadMs = 5 * 60_000): number {
  if (!expiresAtSec) return 0;
  return Math.max(10_000, expiresAtSec * 1000 - nowMs - leadMs);
}

export function tokenIsFresh(expiresAtSec: number, nowMs: number, marginMs = 60_000): boolean {
  return !!expiresAtSec && expiresAtSec * 1000 - nowMs > marginMs;
}

export function fmt(ms: number): string {
  if (!ms || ms < 0) return '0:00';
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;
}
