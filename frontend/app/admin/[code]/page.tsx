'use client';
import { use, useEffect, useState, useCallback } from 'react';
import { api } from '../../../lib/api';

export default function AdminPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const [members, setMembers] = useState<any[]>([]);
  const [queue, setQueue] = useState<any[]>([]);
  const [summary, setSummary] = useState('');
  const [cluster, setCluster] = useState<any>(null);

  const poll = useCallback(async () => {
    try {
      const d = await api(`/party/${code}/poll`);
      setMembers(d.members || []);
      if (d.queue?.length) setQueue(d.queue);
      setSummary(d.ai_summary || '');
      if (d.cluster_info) setCluster(d.cluster_info);
    } catch {}
  }, [code]);

  useEffect(() => { poll(); const i = setInterval(poll, 5000); return () => clearInterval(i); }, [poll]);

  const colors: Record<string, string> = { '0': 'var(--ac)', '1': 'var(--gn)', '2': 'var(--or)', '3': 'var(--bl)' };
  const lb = [...queue].sort((a, b) => b.votes - a.votes).filter(q => q.votes !== 0);

  return (
    <div className="container">
      <div className="page-header">
        <h1>Admin — ML Insights</h1>
        <span className="code">{code}</span>
        <span style={{ fontSize: 12, color: 'var(--tx2)', marginLeft: 'auto' }}>
          {members.length} listeners · {queue.length} tracks
        </span>
      </div>

      {summary && <div className="summary-box">{summary}</div>}

      {/* Clusters */}
      {cluster && cluster.n_clusters > 0 && (
        <div className="card">
          <div className="card-title">Taste Clusters (KMeans, k={cluster.n_clusters})</div>
          <div className="cluster-grid">
            {Object.entries(cluster.clusters).map(([label, ml]: any) => (
              <div key={label} className="cluster-card"
                style={{ borderLeft: `3px solid ${colors[label] || 'var(--tx3)'}` }}>
                <h4 style={{ color: colors[label] || 'var(--tx)', fontSize: 14, marginBottom: 6 }}>
                  Cluster {parseInt(label) + 1}
                </h4>
                <div className="track-meta" style={{ marginBottom: 4 }}>
                  {(cluster.cluster_genres[label] || []).map((g: string) => (
                    <span key={g} className="tag">{g}</span>
                  ))}
                </div>
                <div style={{ fontSize: 12, color: 'var(--tx2)' }}>
                  {ml.map((id: string) => members.find((m: any) => m.id === id)?.display_name || id).join(', ')}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Score Distribution */}
      {queue.length > 0 && (
        <div className="card">
          <div className="card-title">Score Distribution</div>
          {queue.slice(0, 15).map((item: any) => (
            <div key={item.track_id} className="meter-row">
              <span className="meter-label">
                {item.name?.length > 14 ? item.name.slice(0, 14) + '...' : item.name}
              </span>
              <div className="meter-bar">
                <div className="meter-fill" style={{
                  width: `${Math.max((item.score || 0) * 100, 5)}%`,
                  background: 'linear-gradient(90deg, var(--ac), var(--gn))'
                }} />
              </div>
              <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--tx2)', width: 42, textAlign: 'right' }}>
                {item.score?.toFixed(3)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Ranking Formula */}
      <div className="card">
        <div className="card-title">Ranking Formula</div>
        <div style={{ fontFamily: 'monospace', fontSize: 13, color: 'var(--tx2)', lineHeight: 2.2 }}>
          <div><span style={{ color: 'var(--ac)' }}>0.55</span> x avg_user_affinity (genre overlap + energy + danceability)</div>
          <div><span style={{ color: 'var(--gn)' }}>0.30</span> x guest_coverage (% guests matched)</div>
          <div><span style={{ color: 'var(--or)' }}>0.10</span> x popularity (recognizability)</div>
          <div><span style={{ color: 'var(--bl)' }}>0.04</span> x vote_boost (capped +/-5)</div>
        </div>
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--tx3)', borderTop: '1px solid var(--bdr)', paddingTop: 10 }}>
          <strong>Agents:</strong> ProfileAgent &rarr; RankingAgent &rarr; FairnessAgent &rarr; VotingAgent &rarr; LLMAgent<br />
          <strong>ML:</strong> content-based affinity &rarr; KMeans clustering (scikit-learn) &rarr; genre-diversity reranking<br />
          <strong>Fairness:</strong> no same genre 3x in a row
        </div>
      </div>

      {/* Vote Leaderboard */}
      {lb.length > 0 && (
        <div className="card">
          <div className="card-title">Vote Leaderboard</div>
          {lb.map((item: any, idx: number) => (
            <div key={item.track_id} className="track-row"
              style={idx === 0 ? { background: 'var(--acd)', borderRadius: 8 } : {}}>
              <span className="track-rank">{idx + 1}</span>
              <div className="track-info">
                <div className="track-name">{item.name}</div>
                <div className="track-artist">{item.artist}</div>
              </div>
              <span className={`vote-count ${item.votes > 0 ? 'positive' : 'negative'}`}
                style={{ fontSize: 18, fontWeight: 800 }}>
                {item.votes > 0 ? `+${item.votes}` : item.votes}
              </span>
            </div>
          ))}
        </div>
      )}

      {queue.length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: 44, color: 'var(--tx2)' }}>
          <p>Waiting for queue to be generated...</p>
        </div>
      )}
    </div>
  );
}
