'use client';
import {Check} from 'lucide-react';
import type {ReactNode} from 'react';
import './miniapp-check.css';
export function MiniAppCheck({checked,onChange,children,disabled=false}:{checked:boolean;onChange:(value:boolean)=>void;children:ReactNode;disabled?:boolean}){
 return <label className={'ma-check-control'+(checked?' is-checked':'')+(disabled?' is-disabled':'')}><input className="ma-check-native" type="checkbox" checked={checked} disabled={disabled} onChange={e=>onChange(e.target.checked)}/><span className="ma-check-box" aria-hidden="true"><Check size={15} strokeWidth={3}/></span><span className="ma-check-copy">{children}</span></label>
}
