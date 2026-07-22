function readCookie(name: string): string {
  if (typeof document === 'undefined') return '';
  const prefix = `${name}=`;
  const item = document.cookie.split('; ').find((part) => part.startsWith(prefix));
  if (!item) return '';
  return decodeURIComponent(item.slice(prefix.length));
}

function secureHeaders(extra?: HeadersInit): HeadersInit {
  const csrf = readCookie('dbot_csrf_token');
  return {
    Accept: 'application/json',
    'X-Requested-With': 'fetch',
    ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
    ...(extra || {})
  };
}

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    cache: 'no-store',
    headers: secureHeaders({ 'Cache-Control': 'no-cache' })
  });
  const contentType = res.headers.get('content-type') || '';
  const finalPath = (() => {
    try { return new URL(res.url, window.location.origin).pathname; } catch { return ''; }
  })();
  if (res.status === 401 || res.status === 403 || (res.redirected && finalPath === '/login')) {
    throw new Error('AUTH_REQUIRED');
  }
  if (contentType.includes('text/html')) {
    throw new Error(`API returned HTML instead of JSON: ${path}`);
  }
  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.ok) throw new Error(json?.message || json?.detail || `Request failed: ${res.status}`);
  return json as T;
}

export async function submitForm(path: string, data: Record<string, FormDataEntryValue | number | boolean | null | undefined>) {
  const fd = new FormData();
  Object.entries(data).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    if (typeof File !== 'undefined' && value instanceof File) {
      if (value.size > 0) fd.append(key, value);
      return;
    }
    fd.append(key, String(value));
  });
  const res = await fetch(path, {
    method: 'POST',
    body: fd,
    credentials: 'include',
    headers: secureHeaders()
  });
  const contentType = res.headers.get('content-type') || '';
  const finalPath = (() => {
    try { return new URL(res.url, window.location.origin).pathname; } catch { return ''; }
  })();
  if (res.status === 401 || res.status === 403 || (res.redirected && finalPath === '/login')) throw new Error('AUTH_REQUIRED');
  if (contentType.includes('text/html')) throw new Error(`API returned HTML instead of JSON: ${path}`);
  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.ok) throw new Error(json?.message || json?.detail || `Action failed: ${res.status}`);
  return json;
}

export async function getAction(path: string) {
  const res = await fetch(path, {
    credentials: 'include',
    headers: secureHeaders()
  });
  const contentType = res.headers.get('content-type') || '';
  const finalPath = (() => {
    try { return new URL(res.url, window.location.origin).pathname; } catch { return ''; }
  })();
  if (res.status === 401 || res.status === 403 || (res.redirected && finalPath === '/login')) throw new Error('AUTH_REQUIRED');
  if (contentType.includes('text/html')) throw new Error(`API returned HTML instead of JSON: ${path}`);
  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.ok) throw new Error(json?.message || json?.detail || `Action failed: ${res.status}`);
  return json;
}
