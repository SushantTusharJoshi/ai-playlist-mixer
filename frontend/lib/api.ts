const API = process.env.NEXT_PUBLIC_API_BASE || 'https://ai-playlist-mixer-production.up.railway.app';
export async function api(path: string, opts?: RequestInit) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', ...opts?.headers }, cache: 'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
export function apiBase() { return API; }
