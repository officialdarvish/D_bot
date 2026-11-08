'use client';
import { useId } from 'react';

/** Small hardware illustrations, drawn for the resource dashboard. */
export function ResourceIcon({ title }: { title: string }) {
  const id = useId().replace(/:/g, '');
  const kind = /swap/i.test(title) ? 'swap' : /ram|memory/i.test(title) ? 'ram' : /ssd|disk/i.test(title) ? 'disk' : /cpu/i.test(title) ? 'cpu' : 'activity';
  return <span className="resource-emblem" data-kind={kind} aria-hidden="true">
    <svg viewBox="0 0 64 64" fill="none" focusable="false">
      <defs>
        <linearGradient id={`${id}-shell`} x1="12" y1="8" x2="52" y2="58" gradientUnits="userSpaceOnUse"><stop stopColor="currentColor" stopOpacity=".3"/><stop offset="1" stopColor="currentColor" stopOpacity=".04"/></linearGradient>
        <linearGradient id={`${id}-light`} x1="16" y1="12" x2="48" y2="52" gradientUnits="userSpaceOnUse"><stop stopColor="#eff8ff"/><stop offset="1" stopColor="currentColor"/></linearGradient>
      </defs>
      <g stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        {kind === 'cpu' && <>
          <path d="M20 14V8m8 6V8m8 6V8m8 6V8M20 50v6m8-6v6m8-6v6m8-6v6M14 20H8m6 8H8m6 8H8m6 8H8m42-24h6m-6 8h6m-6 8h6m-6 8h6" opacity=".55"/>
          <rect x="14" y="14" width="36" height="36" rx="9" fill={`url(#${id}-shell)`}/>
          <rect x="21" y="21" width="22" height="22" rx="5" stroke={`url(#${id}-light)`}/>
          <path d="M27 32h10M32 27v10" stroke={`url(#${id}-light)`} strokeWidth="2.5"/>
          <path d="M18 22v-3h3m22 26h3v-3" opacity=".8"/>
          <circle cx="46" cy="18" r="1" fill="currentColor" stroke="none"/>
        </>}
        {kind === 'ram' && <>
          <path d="M10 18h44v25H10v-6a4 4 0 0 0 0-8V18Z" fill={`url(#${id}-shell)`}/>
          <path d="M15 43v7h13v-4h5v4h16v-7" stroke={`url(#${id}-light)`}/>
          <path d="M19 44v6m5-6v6m13-6v6m5-6v6m4-6v6" opacity=".65"/>
          {[17,29,41].map(x=><g key={x}><rect x={x} y="24" width="7" height="12" rx="1.8" fill={`url(#${id}-shell)`} stroke={`url(#${id}-light)`}/><path d={`M${x+2} 21v3m3-3v3m-3 12v3m3-3v3`} opacity=".5"/></g>)}
          <path d="M13 15h19m4 0h5M15 40h7m20 0h7" opacity=".4"/>
        </>}
        {kind === 'disk' && <>
          <path d="m14 14 5-4h26l5 4v35l-5 5H19l-5-5V14Z" fill={`url(#${id}-shell)`}/>
          <rect x="19" y="17" width="26" height="25" rx="4" stroke={`url(#${id}-light)`}/>
          <circle cx="32" cy="29" r="8" opacity=".45"/><circle cx="32" cy="29" r="3" fill={`url(#${id}-shell)`}/>
          <path d="m41 38-9-9m4 0-4 0 0 4M23 47h12" stroke={`url(#${id}-light)`}/>
          <circle cx="41" cy="47" r="1.7" fill="currentColor" stroke="none"/>
          <path d="M18 14h2m24 0h2M18 49h2" opacity=".55"/>
        </>}
        {kind === 'swap' && <>
          <rect x="9" y="20" width="18" height="24" rx="5" fill={`url(#${id}-shell)`}/>
          <rect x="37" y="20" width="18" height="24" rx="5" fill={`url(#${id}-shell)`}/>
          <path d="M14 27h8m-8 5h5m23 5h8m-5-5h5" stroke={`url(#${id}-light)`}/>
          <path d="M18 15a18 18 0 0 1 29 0m-7-1 7 1-1-7M46 49a18 18 0 0 1-29 0m7 1-7-1 1 7" stroke={`url(#${id}-light)`} strokeWidth="2"/>
          <path d="m29 28 4 4-4 4m6-8-4 4 4 4" opacity=".65"/>
          <circle cx="18" cy="39" r="1" fill="currentColor" stroke="none"/><circle cx="46" cy="25" r="1" fill="currentColor" stroke="none"/>
        </>}
        {kind === 'activity' && <><rect x="12" y="14" width="40" height="36" rx="10" fill={`url(#${id}-shell)`}/><path d="M18 33h8l5-12 5 23 5-11h5" stroke={`url(#${id}-light)`} strokeWidth="2"/></>}
      </g>
    </svg>
  </span>;
}
