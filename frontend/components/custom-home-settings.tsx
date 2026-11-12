'use client';
import {useEffect,useState} from 'react';
import {fetchJson} from '@/lib/api';
import {useSettingsLanguage} from '@/lib/settings-language';
import {BotHomeSettings} from '@/components/bot-home-settings';
export function CustomHomeSettings({reloadKey,show,setAuthRequired}:any){
 const {s}=useSettingsLanguage();
 const [map,setMap]=useState<Record<string,string>|null>(null),[error,setError]=useState(false),[retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setError(false);void fetchJson<{items:{key:string;value:string}[]}>('/admin/api/v2/settings',controller.signal).then(r=>{if(!controller.signal.aborted)setMap(Object.fromEntries(r.items.map(x=>[x.key,x.value])))}).catch(e=>{if(!controller.signal.aborted){setError(true);if(e.message==='AUTH_REQUIRED')setAuthRequired(true)}});return()=>controller.abort()},[reloadKey,retry,setAuthRequired]);
 if(error)return <section className="card home-message-loading" data-no-i18n="true"><p role="alert">{s('Home message could not be loaded.','پیام صفحه اصلی بارگذاری نشد.')}</p><button className="btn" onClick={()=>setRetry(value=>value+1)}>{s('Try again','تلاش دوباره')}</button></section>;
 return map?<BotHomeSettings key={`${reloadKey}:${map.welcome_text}`} map={map} show={show} setAuthRequired={setAuthRequired} section="home"/>:<section className="card home-message-loading" role="status" data-no-i18n="true">{s('Loading home message…','در حال دریافت پیام صفحه اصلی…')}</section>;
}
