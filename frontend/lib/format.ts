let uiLocale: 'en-US' | 'fa-IR' = 'en-US';
export function setDisplayLanguage(language:'en'|'fa') {uiLocale=language==='fa'?'fa-IR':'en-US';}
function displayLocale() {return uiLocale;}

export function money(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return n.toLocaleString(displayLocale());
}

export function toman(value: number | string | null | undefined) {
  return `${money(value)} ${displayLocale()==='fa-IR'?'تومان':'T'}`;
}

export function gbFromBytes(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return `${(n / 1024 ** 3).toLocaleString(displayLocale(), { maximumFractionDigits: 1 })} ${displayLocale()==='fa-IR'?'گیگابایت':'GB'}`;
}

export function shortDate(value?: string | null) {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '-';
  return d.toLocaleString(displayLocale(), { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function pct(value: number | string | null | undefined) {
  const n = Number(value || 0);
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(1)}%`;
}
