'use client';
import {useEffect,useState} from 'react';
import {fetchJson} from '@/lib/api';
import {BotHomeSettings} from '@/components/bot-home-settings';
export function CustomHomeSettings({reloadKey,show,setAuthRequired}:any){
 const [map,setMap]=useState<Record<string,string>|null>(null);
 const [error,setError]=useState(false);
 useEffect(()=>{let live=true;setError(false);void fetchJson<{items:{key:string;value:string}[]}>('/admin/api/v2/settings').then(r=>{if(live)setMap(Object.fromEntries(r.items.map(x=>[x.key,x.value])))}).catch(e=>{if(live){setError(true);if(e.message==='AUTH_REQUIRED')setAuthRequired(true)}});return()=>{live=false}},[reloadKey,setAuthRequired]);
 return map?<BotHomeSettings key={reloadKey} map={map} show={show} setAuthRequired={setAuthRequired} section="home"/>:error?<p role="alert">Home message could not be loaded.</p>:null;
}
