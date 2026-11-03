'use client';
import {useEffect,useRef,type ReactNode} from 'react';

/** Keep focus and scrolling inside admin dialogs; restore both on close. */
export function AdminDialog({label,onClose,children,busy=false}:{label:string;onClose:()=>void;children:ReactNode;busy?:boolean}) {
 const root=useRef<HTMLDivElement>(null),close=useRef(onClose),pending=useRef(busy);
 close.current=onClose;pending.current=busy;
 useEffect(()=>{
  const previous=document.activeElement as HTMLElement|null,overflow=document.body.style.overflow;
  document.body.style.overflow='hidden';
  const dialog=root.current;
  const controls=()=>Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled):not([type="hidden"]),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')||[]).filter(n=>n.getClientRects().length>0);
  const frame=requestAnimationFrame(()=>(dialog?.querySelector<HTMLElement>('input:not([type="hidden"]):not(:disabled),select:not(:disabled),textarea:not(:disabled)')||controls()[0]||dialog)?.focus());
  const onKey=(e:KeyboardEvent)=>{
   if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if(!pending.current)close.current();}
   if(e.key!=='Tab')return;
   const nodes=controls(),first=nodes[0],last=nodes[nodes.length-1];
   if(!first){e.preventDefault();dialog?.focus();return;}
   if(!dialog?.contains(document.activeElement)||(e.shiftKey&&document.activeElement===first)||(!e.shiftKey&&document.activeElement===last)){e.preventDefault();(e.shiftKey?last:first).focus();}
  };
  document.addEventListener('keydown',onKey,true);
  return()=>{cancelAnimationFrame(frame);document.removeEventListener('keydown',onKey,true);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus();};
 },[]);
 return <div ref={root} className="modal-backdrop" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>{children}</div>;
}
