'use client';
import {useSettingsLanguage} from '@/lib/settings-language';
import {MiniAppCheck} from './miniapp-check';
import { useState } from 'react';
import { Bot, Check, ExternalLink, Plus, Save, ShieldCheck, Users, X } from 'lucide-react';
import { fetchJson, submitForm } from '@/lib/api';
import { useEffect } from 'react';

type Config = { enabled:boolean; title:string; welcome:string; menu_text:string; support_username:string; accent:string; animations:boolean; fullscreen:boolean; show_buy:boolean; show_wallet:boolean; show_services:boolean; show_support:boolean; reseller_enabled:boolean; reseller_requests:boolean; links:{label:string;url:string}[] };
const switches: {key:keyof Config;label:string}[] = [
  {key:'enabled',label:'Enable Mini App / فعال بودن مینی‌اپ'},
  {key:'animations',label:'Animated background / انیمیشن پس‌زمینه'},
  {key:'fullscreen',label:'Fullscreen on supported Telegram clients / تمام‌صفحه'},
  {key:'show_buy',label:'Buy subscriptions / خرید اشتراک'},
  {key:'show_wallet',label:'Wallet / کیف پول'},
  {key:'show_services',label:'My configs / کانفیگ‌های من'},
  {key:'show_support',label:'Direct support chat / ارتباط مستقیم پشتیبانی'},
  {key:'reseller_enabled',label:'Reseller workspace / محیط نمایندگی'},
  {key:'reseller_requests',label:'Allow reseller requests / درخواست نمایندگی در ربات'},
];
export function MiniAppSettings({reloadKey,setAuthRequired,show}:any){
  const [draft,setDraft]=useState<Config|null>(null); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  useEffect(()=>{let live=true;fetchJson<{config:Config}>('/admin/api/v2/miniapp').then(r=>{if(live)setDraft(r.config)}).catch(e=>{if(e.message==='AUTH_REQUIRED')setAuthRequired(true);if(live)setError(e.message)});return()=>{live=false}},[reloadKey,setAuthRequired]);
  async function save(){setBusy(true);try{const r:any=await submitForm('/admin/miniapp/save',{config_json:JSON.stringify(draft)});show(r?.message||'Mini App saved',!r?.menu_sync_pending);}catch(e){const msg=(e as Error).message;if(msg==='AUTH_REQUIRED')setAuthRequired(true);show(msg,false)}finally{setBusy(false)}}
  if(!draft)return <div className="card">{error||'Loading Mini App settings…'}</div>;
  return <div className="miniapp-admin"><section className="card"><div className="panel-head"><h2><Bot size={22}/> MINI APP</h2><span className={'badge '+(draft.enabled?'green':'red')}>{draft.enabled?'Enabled':'Disabled'}</span></div>
    <div className="miniapp-form-grid">{([{key:'title',label:'App title / نام اپلیکیشن'},{key:'support_username',label:'Support username / یوزرنیم مدیر پشتیبانی'},{key:'welcome',label:'Home subtitle / متن زیر عنوان'}] as const).map(f=><label key={f.key}>{f.label}<input value={draft[f.key]} maxLength={f.key==='welcome'?180:60} placeholder={f.key==='support_username'?'@your_support':undefined} onChange={e=>setDraft({...draft,[f.key]:e.target.value})}/></label>)}<label>Accent color / رنگ اصلی<input type="color" value={draft.accent} onChange={e=>setDraft({...draft,accent:e.target.value})}/></label></div>
    <p className="muted" dir="rtl">نام دکمهٔ کنار چت به‌صورت خودکار از نام ربات در تلگرام دریافت می‌شود.</p>
    <div className="miniapp-switches">{switches.map(s=><MiniAppCheck key={s.key} checked={Boolean(draft[s.key])} onChange={checked=>setDraft({...draft,[s.key]:checked})}>{s.label}</MiniAppCheck>)}</div>
  </section><section className="card"><div className="panel-head"><h3>Shortcuts / لینک‌های دلخواه</h3><button className="btn" disabled={draft.links.length>=6} onClick={()=>setDraft({...draft,links:[...draft.links,{label:'',url:''}]})}><Plus size={16}/>Add link</button></div>{draft.links.map((l,i)=><div className="miniapp-shortcut-row" key={i}><input aria-label={'Link title '+(i+1)} placeholder="عنوان لینک" value={l.label} onChange={e=>setDraft({...draft,links:draft.links.map((v,n)=>n===i?{...v,label:e.target.value}:v)})}/><input aria-label={'Link URL '+(i+1)} placeholder="https://..." value={l.url} onChange={e=>setDraft({...draft,links:draft.links.map((v,n)=>n===i?{...v,url:e.target.value}:v)})}/><button className="btn danger" aria-label="Remove shortcut" onClick={()=>setDraft({...draft,links:draft.links.filter((_,n)=>n!==i)})}><X size={16}/></button></div>)}</section><div className="card-actions"><button className="btn primary" disabled={busy} onClick={save}><Save size={16}/>{busy?'Saving…':'Save Mini App'}</button></div>
  <style jsx>{`.miniapp-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.miniapp-admin label{display:grid;gap:8px;color:#bac9dc;font-size:13px}.miniapp-admin input:not([type=checkbox]){width:100%;padding:11px;border:1px solid #314056;border-radius:10px;background:#101c30;color:white}.miniapp-admin input[type=color]{height:45px}.miniapp-switches{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:24px}.miniapp-switches label{display:flex;align-items:center;gap:10px;border:1px solid #26364c;border-radius:12px;padding:13px}.miniapp-shortcut-row{display:grid;grid-template-columns:1fr 2fr auto;gap:10px;margin-top:12px}.miniapp-admin .card{margin-bottom:20px;padding:22px}.miniapp-admin h2{display:flex;align-items:center;gap:9px}@media(max-width:650px){.miniapp-form-grid,.miniapp-switches,.miniapp-shortcut-row{grid-template-columns:1fr}}`}</style></div>
}

export function AccessRuleCards({map,show,setAuthRequired}:any){
 const {s,failure}=useSettingsLanguage();
 const [rules,setRules]=useState(String(map.rules_text||'')),[rulesOn,setRulesOn]=useState(map.rules_enabled==='1');
 const [joinOn,setJoinOn]=useState(map.force_join_enabled==='1'),[channel,setChannel]=useState(String(map.channel_url||'')),[busy,setBusy]=useState('');
 async function save(kind:string){
  setBusy(kind);
  try{await submitForm('/admin/settings/'+kind,kind==='rules'?{enabled:rulesOn?'1':'0',rules_text:rules}:{enabled:joinOn?'1':'0',channel_url:channel});show(s('Settings saved.','تنظیمات ذخیره شد.'),true);}
  catch(e){if((e as Error).message==='AUTH_REQUIRED')setAuthRequired(true);show(failure(e),false);}finally{setBusy('');}
 }
 return <>
 <section className="card settings-card access-rule" data-no-i18n="true">
  <div className="settings-card-head"><ShieldCheck size={20}/><div><h2>{s('Rules and acceptance','قوانین و پذیرش کاربر')}</h2><p className="muted">{s('Set the service rules and require acceptance before entry.','قوانین سرویس و الزام پذیرش آن پیش از ورود را تنظیم کنید.')}</p></div></div>
  <MiniAppCheck checked={rulesOn} onChange={setRulesOn}>{s('Require users to accept the rules','دریافت تأیید قوانین از کاربران')}</MiniAppCheck>
  <label className="form-field"><span>{s('Rules text','متن قوانین')}</span><textarea dir="auto" rows={5} value={rules} placeholder={s('Enter your service rules','متن قوانین سرویس را وارد کنید')} onChange={e=>setRules(e.target.value)}/></label>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy} onClick={()=>void save('rules')}><Save size={16}/>{busy==='rules'?s('Saving…','در حال ذخیره…'):s('Save rules','ذخیره قوانین')}</button></div>
 </section>
 <section className="card settings-card access-rule" data-no-i18n="true">
  <div className="settings-card-head"><Users size={20}/><div><h2>{s('Required channel membership','عضویت اجباری در کانال')}</h2><p className="muted">{s('Ask users to join your channel before using the bot.','پیش از استفاده از ربات، عضویت کاربران در کانال را بررسی کنید.')}</p></div></div>
  <MiniAppCheck checked={joinOn} onChange={setJoinOn}>{s('Require channel membership','فعال‌کردن عضویت اجباری')}</MiniAppCheck>
  <label className="form-field"><span>{s('Channel username or URL','نام کاربری یا لینک کانال')}</span><input dir="ltr" value={channel} onChange={e=>setChannel(e.target.value)} placeholder="@channel / https://t.me/channel"/></label>
  <p className="settings-help">{s('The bot must be an administrator in this channel to verify membership.','برای بررسی عضویت، ربات باید در این کانال مدیر باشد.')}</p>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy} onClick={()=>void save('force-join')}><Save size={16}/>{busy==='force-join'?s('Saving…','در حال ذخیره…'):s('Save channel','ذخیره کانال')}</button></div>
 </section></>;
}

