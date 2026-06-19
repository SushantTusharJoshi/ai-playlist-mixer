'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '../lib/api';

export default function Home() {
  const router = useRouter();
  const [joinCode, setJoinCode] = useState('');
  const [creating, setCreating] = useState(false);

  async function create() {
    setCreating(true);
    try {
      const d = await api('/party/create', { method: 'POST', body: JSON.stringify({ host_id: 'host', theme: 'party' }) });
      router.push(`/host/${d.code}`);
    } catch { alert('Failed'); }
    setCreating(false);
  }

  return (
    <div className="landing">
      <div style={{ fontSize: 52, marginBottom: 16 }}>🎵</div>
      <h1>AI Playlist Mixer</h1>
      <p className="sub">Everyone joins. AI blends your tastes. The group votes. No more music dictators.</p>
      <button className="btn btn-primary" onClick={create} disabled={creating} style={{ padding: '14px 36px', fontSize: 16, borderRadius: 24 }}>
        {creating ? 'Creating...' : 'Create a Party'}
      </button>
      <div style={{ display: 'flex', gap: 8, marginTop: 24 }}>
        <input className="input" placeholder="PARTY CODE" maxLength={6} value={joinCode}
          onChange={e => setJoinCode(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && joinCode.length >= 4 && router.push(`/party/${joinCode}`)}
          style={{ width: 160, textAlign: 'center', fontFamily: 'monospace', fontSize: 16, letterSpacing: 3 }} />
        <button className="btn btn-secondary" onClick={() => joinCode.length >= 4 && router.push(`/party/${joinCode}`)}>Join</button>
      </div>
      <p style={{ marginTop: 10, fontSize: 12, color: 'var(--tx3)' }}>Enter a code to join as guest</p>
    </div>
  );
}
