// Resolve managed website routes before fetch: POST redirects are deliberately blocked.
export function publicWebPath(path: string): string {
  if (typeof window === 'undefined') return path;
  if (!/^\/(admin|login|logout|setup)(?=\/|[?#]|$)/.test(path)) return path;
  const match = window.location.pathname.match(/^\/([^/]+)\/(?:admin|login|logout|setup)(?=\/|$)/);
  return match ? `/${match[1]}${path}` : path;
}
