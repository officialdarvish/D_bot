'use client';
import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {PackageCheck,Download,RefreshCw,X} from 'lucide-react';
import {fetchJson,submitForm} from '@/lib/api';
import {useUiLanguage} from '@/lib/ui-language';
type Info={installed:{version:string;build:number};latest?:{version:string;build:number;notes:{fa:string;en:string}};available:boolean;commit?:string;host_ready:boolean;check_error?:string;job:{state:string;error?:string;backup?:string}};
export function SystemUpdate(){
 const {language}=useUiLanguage(),fa=language==='fa';
 const [info,setInfo]=useState<Info|null>(null),[open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const dialog=useRef<HTMLDialogElement>(null);
 async function load(force=false){try{setInfo(await fetchJson<Info>('/admin/api/v2/update'+(force?'?force=true':'')));setError('')}catch(e){setError(e instanceof Error?e.message:String(e))}}
 useEffect(()=>{void load();const t=setInterval(()=>void load(),15000);return()=>clearInterval(t)},[]);
 useEffect(()=>{if(open)dialog.current?.showModal()},[open]);
 async function start(){if(!info?.commit)return;setBusy(true);setError('');try{await submitForm('/admin/update/start',{commit:info.commit});await load()}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
 const running=!!info&&['queued','checking','backing_up','building','restarting'].includes(info.job.state);
 const problem=error||info?.check_error;
 const state=running?(fa?'در حال به‌روزرسانی':'Updating'):problem?(fa?'بررسی ناموفق':'Check failed'):info?.available?(fa?'آپدیت جدید موجود است':'Update available'):info?(fa?'به‌روز است':'Up to date'):(fa?'در حال بررسی':'Checking');
 const jobLabels:Record<string,string>={queued:fa?'در صف اجرا':'Queued',checking:fa?'بررسی آپدیت':'Checking update',backing_up:fa?'پشتیبان‌گیری دیتابیس':'Backing up database',building:fa?'ساخت نسخه جدید':'Building update',restarting:fa?'راه‌اندازی مجدد':'Restarting',completed:fa?'آپدیت کامل شد':'Update completed',failed:fa?'آپدیت ناموفق بود':'Update failed'};
 return <section className="panel version-card" data-no-i18n="true" dir={fa?'rtl':'ltr'}>
  <div className="panel-head"><div className="settings-card-head"><PackageCheck size={21}/><h2>{fa?'نسخه':'Version'}</h2></div><span className={`badge ${problem?'yellow':info?.available?'blue':'green'}`} role="status">{state}</span></div>
  <div className="version-current"><strong dir="ltr">{info?`v${info.installed.version}`:'—'}</strong><span className="muted">{fa?'بیلد':'Build'} {info?.installed.build??'—'}</span></div>
  {info?.available&&info.latest&&<p className="muted">{fa?'نسخه جدید:':'Latest:'} <b dir="ltr">v{info.latest.version} · {info.latest.build}</b></p>}
  {problem&&<p className="settings-error" role="alert">{problem}</p>}
  <div className="settings-actions"><button type="button" className={`btn ${info?.available?'primary':''}`} onClick={()=>setOpen(true)} disabled={!info}><Download size={16}/>{fa?'جزئیات و آپدیت':'Details and update'}</button><button type="button" className="btn" onClick={()=>void load(true)} disabled={busy||running} aria-label={fa?'بررسی دوباره':'Check again'}><RefreshCw size={16}/></button></div>
  {open&&createPortal(<dialog ref={dialog} className="modal-card version-dialog" data-no-i18n="true" dir={fa?'rtl':'ltr'} aria-labelledby="version-dialog-title" onClose={()=>setOpen(false)} onCancel={()=>setOpen(false)}>
   <div className="modal-head"><h2 id="version-dialog-title">{fa?'به‌روزرسانی D BOT':'Update D BOT'}</h2><button type="button" className="btn" onClick={()=>setOpen(false)} aria-label={fa?'بستن':'Close'}><X size={18}/></button></div>
   <p>{fa?'نسخه نصب‌شده:':'Installed:'} <b dir="ltr">v{info?.installed.version} · {info?.installed.build}</b></p>
   {info?.latest&&<><p>{fa?'آخرین نسخه:':'Latest:'} <b dir="ltr">v{info.latest.version} · {info.latest.build}</b></p><p className="version-notes">{info.latest.notes?.[fa?'fa':'en']}</p></>}
   <p className="muted">{fa?'ابتدا پشتیبان دیتابیس گرفته می‌شود، سپس ربات بازسازی و راه‌اندازی می‌شود. در این مدت پنل موقتاً قطع می‌شود.':'The updater backs up the database, rebuilds and restarts the bot. The panel will be temporarily unavailable.'}</p>
   {!info?.host_ready&&<p className="settings-error">{fa?'برای فعال‌شدن آپدیت وب، یک‌بار روی VPS دستور dbot update را اجرا کنید.':'Run dbot update once on the VPS to enable web updates.'}</p>}
   {running&&<p role="status">{jobLabels[info!.job.state]}</p>}
   {info?.job.backup&&<p className="muted version-notes">{fa?'پشتیبان:':'Backup:'} {info.job.backup}</p>}
   {(error||info?.job.error||info?.check_error)&&<p className="settings-error" role="alert">{error||info?.job.error||info?.check_error}</p>}
   <div className="settings-actions"><button type="button" className="btn primary" disabled={busy||running||!info?.available||!info?.host_ready||!!info?.check_error} onClick={()=>void start()}><Download size={16}/>{fa?'تأیید و آپدیت VPS':'Confirm and update VPS'}</button><button type="button" className="btn" onClick={()=>setOpen(false)}>{fa?'بستن':'Close'}</button></div>
  </dialog>,document.body)}
 </section>;
}
