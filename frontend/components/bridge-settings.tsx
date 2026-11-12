'use client';
import {useEffect,useState} from 'react';
import {Save,Network} from 'lucide-react';
import {fetchJson,submitForm} from '@/lib/api';
import {publicWebPath} from '@/lib/web-path';
import {useUiLanguage} from '@/lib/ui-language';
export type BridgeSettingsInfo={ok:boolean;config:{enabled:boolean;url:string;bot_username:string;currency:string};key_saved:boolean;secret_saved:boolean};
export function BridgeSettings({onSaved,onAuthRequired}:{onSaved?:()=>void;onAuthRequired?:()=>void}={}){
 const {language}=useUiLanguage(),fa=language==='fa';
 const [form,setForm]=useState({enabled:false,url:'',bot_username:'',currency:'USDT',key:'',secret:''}),[credentials,setCredentials]=useState({key:false,secret:false}),[loaded,setLoaded]=useState(false),[message,setMessage]=useState(''),[failed,setFailed]=useState(false),[busy,setBusy]=useState(false);
 function failure(e:unknown){const msg=e instanceof Error?e.message:String(e);if(msg==='AUTH_REQUIRED')onAuthRequired?.();setFailed(true);const messages:Record<string,string>={'AUTH_REQUIRED':'نشست ورود منقضی شده است؛ دوباره وارد شوید.','Bridge connection failed':'اتصال به بریج برقرار نشد؛ آدرس و وضعیت سرویس را بررسی کنید.','Bridge settings or capabilities are invalid; verify the companion configuration.':'تنظیمات یا قابلیت‌های بریج معتبر نیست؛ ارز و پشتیبانی محصولات دیجیتال را بررسی کنید.'};setMessage(fa?(messages[msg]||msg):msg)}
 async function load(){try{const r=await fetchJson<BridgeSettingsInfo>('/admin/api/v2/darvish-bridge');setForm(f=>({...f,...r.config}));setCredentials({key:r.key_saved,secret:r.secret_saved});setLoaded(true);setFailed(false);setMessage('')}catch(e){failure(e)}}
 useEffect(()=>{void load()},[]);
 async function save(e:React.FormEvent){e.preventDefault();setBusy(true);setMessage('');setFailed(false);try{await submitForm('/admin/darvish-bridge/save',{...form,enabled:form.enabled?'1':'0'});await load();setForm(f=>({...f,key:'',secret:''}));setMessage(fa?'تنظیمات ذخیره شد؛ اتصال و قابلیت پرداخت هنگام فعال‌سازی بررسی شدند.':'Settings saved. Connection and payment capability are checked when enabled.');onSaved?.()}catch(e){failure(e)}finally{setBusy(false)}}
 const webhook=typeof window!=='undefined'?window.location.origin+publicWebPath('/webhooks/darvish-bridge'):'';
 return <form className="bridge-connection-form" onSubmit={e=>void save(e)} aria-busy={!loaded||busy}>
  <div className="settings-card-head"><Network size={21}/><p className="muted">{fa?'اتصال پرداخت بریج برای ربات و مینی‌اپ':'Bridge payment connection for the bot and Mini App'}</p></div>
  <label className="miniapp-check"><input type="checkbox" checked={form.enabled} disabled={!loaded||busy} onChange={e=>setForm({...form,enabled:e.target.checked})}/>{fa?'فعال‌سازی Darvish Bridge':'Enable Darvish Bridge'}</label>
  <div className="settings-form-grid">{(['url','bot_username','key','secret'] as const).map(key=><label className="form-field" key={key}>{({url:fa?'آدرس HTTPS بریج':'Bridge HTTPS URL',bot_username:fa?'نام کاربری ربات بریج':'Bridge bot username',key:'API key',secret:'Webhook secret'})[key]}<input dir="ltr" disabled={!loaded||busy} type={['key','secret'].includes(key)?'password':key==='url'?'url':'text'} autoComplete="off" required={form.enabled&&(!['key','secret'].includes(key)||!credentials[key as 'key'|'secret'])} value={form[key]} placeholder={credentials[key as 'key'|'secret']?(fa?'ذخیره شده؛ برای حفظ خالی بگذارید':'Saved; leave blank to retain'):key==='url'?'https://bridge.example.com':''} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}<label className="form-field">{fa?'ارز پرداخت':'Payment currency'}<select disabled={!loaded||busy} value={form.currency||'USDT'} onChange={e=>setForm({...form,currency:e.target.value})}><option>USDT</option><option>USD</option></select></label></div>
  <div className="bridge-webhook"><span className="muted">{fa?'آدرس وب‌هوک فروشنده در بریج':'Merchant webhook URL in Bridge'}</span><code dir="ltr">{webhook}</code></div>
  <p className="settings-help">{fa?'هنگام فعال‌سازی، اتصال و پشتیبانی ارز انتخاب‌شده و محصولات دیجیتال بررسی می‌شود. کلیدها رمزنگاری و با پرداخت‌های ربات و مینی‌اپ مشترک ذخیره می‌شوند.':'Enabling validates the connection, selected currency and digital product support. Credentials are encrypted and shared by bot and Mini App payments.'}</p>
  {message&&<p className={failed?'settings-error':'muted'} role={failed?'alert':'status'}>{message}</p>}
  <div className="settings-actions"><button type="submit" className="btn primary" disabled={busy||!loaded}><Save size={16}/>{busy?(fa?'در حال بررسی…':'Checking…'):(fa?'بررسی اتصال و ذخیره':'Validate connection and save')}</button>{!loaded&&failed&&<button type="button" className="btn" onClick={()=>void load()}>{fa?'تلاش مجدد':'Retry'}</button>}</div>
 </form>;
}
