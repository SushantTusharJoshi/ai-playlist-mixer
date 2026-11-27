// Run with `npm test` (node --test, Node 23.6+ strips the types; no extra packages).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_NP, createAdvanceGuard, fmt, isSpotifyTrackEnd, mergeNowPlaying, normalize,
  playableAs, positionAt, refreshDelayMs, tokenIsFresh, youtubeIdOf,
} from './player-state.ts';
import type { NowPlaying } from './player-state.ts';

const np = (over: Partial<NowPlaying>): NowPlaying => ({
  ...EMPTY_NP, track_id: 'yt-dQw4w9WgXcQ', name: 'A', artist: 'B', seq: 1, source: 'youtube',
  is_playing: true, updated_at: 1000, ...over,
});

test('a poll with an older seq never replaces a newer track', () => {
  const afterNext = np({ seq: 5, track_id: 'yt-jNQXAC9IVRw' });
  const stalePoll = np({ seq: 4 });
  assert.equal(mergeNowPlaying(afterNext, stalePoll), afterNext);
});

test('an unchanged poll keeps the same object, so nothing re-renders or reloads', () => {
  const cur = np({});
  assert.equal(mergeNowPlaying(cur, { ...cur }), cur);
});

test('a pause on the same track is taken, an older pause report is not', () => {
  const cur = np({ updated_at: 1000 });
  const paused = np({ updated_at: 1005, is_playing: false, position_ms: 5000 });
  assert.equal(mergeNowPlaying(cur, paused), paused);
  assert.equal(mergeNowPlaying(paused, np({ updated_at: 1001 })), paused);
});

test('the first poll replaces the empty state', () => {
  const first = normalize({ track_id: '', is_playing: false });
  assert.equal(first.seq, 0);
  assert.equal(mergeNowPlaying(EMPTY_NP, first), first);
});

test('normalize fills fields an older backend does not send', () => {
  const old = normalize({ track_id: 'yt-x', name: 'n', artist: 'a', youtube_id: 'dQw4w9WgXcQ', is_playing: true, started_at: 50 });
  assert.equal(old.source, 'youtube');
  assert.equal(old.updated_at, 50);
});

test('progress moves while playing and stops when paused or at the end', () => {
  const playing = np({ position_ms: 10_000, updated_at: 100, duration_ms: 60_000 });
  assert.equal(positionAt(playing, 105_000), 15_000);
  assert.equal(positionAt(playing, 500_000), 60_000);
  assert.equal(positionAt({ ...playing, is_playing: false }, 105_000), 10_000);
  assert.equal(positionAt(EMPTY_NP, 105_000), 0);
});

test('youtube ids: real videos only, not the search-link fallback', () => {
  assert.equal(youtubeIdOf({ track_id: 'yt-dQw4w9WgXcQ' }), 'dQw4w9WgXcQ');
  assert.equal(youtubeIdOf({ track_id: 'yt-search-daft%20punk' }), null);
  assert.equal(youtubeIdOf({ track_id: 'p01', youtube_id: 'jNQXAC9IVRw' }), 'jNQXAC9IVRw');
});

test('which rows the host can play', () => {
  const sp = { track_id: 'sp-1', name: 'n', artist: 'a', uri: 'spotify:track:1' };
  assert.equal(playableAs(sp, true, false), 'spotify');
  assert.equal(playableAs(sp, false, false), null);
  assert.equal(playableAs(sp, false, true), 'match');  // no Spotify login: matched to YouTube (party CDZ174)
  assert.equal(playableAs({ track_id: 'p01', name: 'n', artist: 'a' }, false, true), 'match');
  assert.equal(playableAs({ track_id: 'p01', name: 'n', artist: 'a' }, false, false), null);
});

test('track end, error skip and a tap for the same track advance once', () => {
  const guard = createAdvanceGuard();
  assert.equal(guard.claim(3), true);   // ended event
  assert.equal(guard.claim(3), false);  // error auto-skip for the same track
  assert.equal(guard.claim(2), false);  // a late event from the previous track
  assert.equal(guard.claim(4), true);   // the next track can advance again
});

test('spotify end detection', () => {
  const uri = 'spotify:track:1';
  const near = { paused: false, position: 198_500, duration: 200_000, previousUris: [], currentUri: uri };
  const ended = { paused: true, position: 0, duration: 200_000, previousUris: [], currentUri: uri };
  assert.equal(isSpotifyTrackEnd(near, ended, uri), true);
  assert.equal(isSpotifyTrackEnd(null, { ...ended, previousUris: [uri] }, uri), true);
  // paused by the user mid-track is not an end
  assert.equal(isSpotifyTrackEnd({ ...near, position: 50_000 }, { ...ended, position: 50_000 }, uri), false);
  // a fresh load reports position 0 but the old track was far from its end
  assert.equal(isSpotifyTrackEnd({ ...near, position: 3_000 }, ended, uri), false);
});

test('token refresh is scheduled 5 minutes before expiry', () => {
  const now = 1_000_000;
  assert.equal(refreshDelayMs(now / 1000 + 3600, now), 3600_000 - 300_000);
  assert.equal(refreshDelayMs(now / 1000 + 30, now), 10_000);
  assert.equal(refreshDelayMs(0, now), 0);
  assert.equal(tokenIsFresh(now / 1000 + 3600, now), true);
  assert.equal(tokenIsFresh(now / 1000 + 30, now), false);
  assert.equal(tokenIsFresh(0, now), false);
});

test('time format', () => {
  assert.equal(fmt(0), '0:00');
  assert.equal(fmt(61_000), '1:01');
});
