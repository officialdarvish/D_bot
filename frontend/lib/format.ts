export function money(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return n.toLocaleString('en-US');
}

export function toman(value: number | string | null | undefined) {
  return `${money(value)} T`;
}

export function gbFromBytes(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return `${(n / 1024 ** 3).toLocaleString('en-US', { maximumFractionDigits: 1 })} GB`;
}

export function shortDate(value?: string | null) {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '-';
  return d.toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function pct(value: number | string | null | undefined) {
  const n = Number(value || 0);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(1)}%`;
}
