const API = process.env.NEXT_PUBLIC_API_BASE || 'https://ai-playlist-mixer-production.up.railway.app';
export async function api(path: string, opts?: RequestInit) {
  const r = await fetch(`${API}${path}`, { ...opts, headers: { 'Content-Type': 'application/json', ...opts?.headers }, cache: 'no-store' });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
export function apiBase() { return API; }

// The host key is returned once by /party/create and kept on the device that
// created the party. Host-only calls send it as X-Host-Key.
function keyName(code: string) { return `host-key:${code}`; }
export function saveHostKey(code: string, key: string) {
  try { localStorage.setItem(keyName(code), key); } catch {}
}
export function loadHostKey(code: string): string {
  try { return localStorage.getItem(keyName(code)) || ''; } catch { return ''; }
}
export function hostHeaders(code: string): Record<string, string> {
  const k = loadHostKey(code);
  return k ? { 'X-Host-Key': k } : {};
}
