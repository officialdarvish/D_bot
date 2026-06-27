import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
export function money(v: number | string | null | undefined) { return new Intl.NumberFormat('en-US').format(Number(v || 0)); }
export function pct(v: number | string | null | undefined) { const n = Number(v || 0); return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`; }
export function statusTone(status?: string) { const s=(status||'').toLowerCase(); if(['paid','approved','completed','active'].includes(s)) return 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10'; if(['pending','review'].includes(s)) return 'text-amber-300 border-amber-400/30 bg-amber-400/10'; return 'text-rose-300 border-rose-400/30 bg-rose-400/10'; }
