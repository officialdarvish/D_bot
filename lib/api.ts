export const API = process.env.NEXT_PUBLIC_API_PREFIX || '';
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...init, credentials: 'include', headers: { 'accept': 'application/json', ...(init.headers || {}) }, cache: 'no-store' });
  if (res.status === 307 || res.redirected) { if (typeof window !== 'undefined') window.location.href = '/login?next=/dashboard'; }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
export async function postForm(path: string, data: Record<string, any>) {
  const form = new FormData(); Object.entries(data).forEach(([k,v]) => form.append(k, v == null ? '' : String(v)));
  const res = await fetch(`${API}${path}`, { method: 'POST', body: form, credentials: 'include', headers: { 'x-requested-with': 'fetch', 'accept': 'application/json' } });
  const json = await res.json().catch(() => ({})); if (!res.ok || json.ok === false) throw new Error(json.message || 'Request failed'); return json;
}
export async function actionGet(path: string) {
  const res = await fetch(`${API}${path}${path.includes('?')?'&':'?'}ajax=1`, { credentials: 'include', headers: { 'x-requested-with': 'fetch', 'accept': 'application/json' } });
  const json = await res.json().catch(() => ({})); if (!res.ok || json.ok === false) throw new Error(json.message || 'Request failed'); return json;
}
