export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-Requested-With': 'fetch' }
  });
  const contentType = res.headers.get('content-type') || '';
  if (res.redirected || contentType.includes('text/html')) {
    throw new Error('AUTH_REQUIRED');
  }
  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.ok) throw new Error(json?.message || json?.detail || `Request failed: ${res.status}`);
  return json as T;
}

export async function submitForm(path: string, data: Record<string, FormDataEntryValue | number | boolean | null | undefined>) {
  const fd = new FormData();
  Object.entries(data).forEach(([key, value]) => {
    if (value !== undefined && value !== null) fd.append(key, String(value));
  });
  const res = await fetch(path, {
    method: 'POST',
    body: fd,
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-Requested-With': 'fetch' }
  });
  const contentType = res.headers.get('content-type') || '';
  if (res.redirected || contentType.includes('text/html')) throw new Error('AUTH_REQUIRED');
  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.ok) throw new Error(json?.message || json?.detail || `Action failed: ${res.status}`);
  return json;
}

export async function getAction(path: string) {
  const res = await fetch(path, {
    credentials: 'include',
    headers: { Accept: 'application/json', 'X-Requested-With': 'fetch' }
  });
  const contentType = res.headers.get('content-type') || '';
  if (res.redirected || contentType.includes('text/html')) throw new Error('AUTH_REQUIRED');
  const json = await res.json().catch(() => null);
  if (!res.ok || !json?.ok) throw new Error(json?.message || json?.detail || `Action failed: ${res.status}`);
  return json;
}
