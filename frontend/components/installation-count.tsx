'use client';
import {useEffect,useState} from 'react';
import {Users} from 'lucide-react';
import {fetchJson} from '@/lib/api';
export function InstallationCount(){
 const [count,setCount]=useState<number|null>(null);
 useEffect(()=>{let alive=true;const update=()=>void fetchJson<{count:number|null}>('/admin/api/v2/installation-count').then(r=>{if(alive)setCount(r.count)}).catch(()=>{if(alive)setCount(null)});update();const timer=setInterval(update,60000);return()=>{alive=false;clearInterval(timer)}},[]);
 return <div className="installation-count" data-no-i18n="true"><Users size={18}/><span>D Bot User</span><strong>{count===null?'—':count.toLocaleString('en-US')}</strong></div>;
}
