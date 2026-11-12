'use client';
import {useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {PackageCheck,Download,RefreshCw,X,Server} from 'lucide-react';
import {AdminDialog} from '@/components/admin-dialog';
import {fetchJson,submitForm} from '@/lib/api';
import {useUiLanguage} from '@/lib/ui-language';
type Job={id?:string;state:string;error?:string;backup?:string};
type Info={installed:{version:string;build:number};latest?:{version:string;build:number;notes:{fa:string;en:string}};available:boolean;commit?:string;host_ready:boolean;host?:{reason:string;bootstrap_command:string};check_error?:string;job:Job};
export function SystemUpdate(){
 const {language}=useUiLanguage(),fa=language==='fa';
 const [info,setInfo]=useState<Info|null>(null),[open,setOpen]=useState(false),[busy,setBusy]=useState(false),[checking,setChecking]=useState(false),[error,setError]=useState(''),[fetchError,setFetchError]=useState('');
 async function load(force=false){if(force)setChecking(true);try{setInfo(await fetchJson<Info>('/admin/api/v2/update'+(force?'?force=true':'')));setFetchError('')}catch(e){setFetchError(e instanceof Error?e.message:String(e))}finally{if(force)setChecking(false)}}
 useEffect(()=>{void load();const t=setInterval(()=>void load(),5000);return()=>clearInterval(t)},[]);
 async function start(){if(!info?.commit||busy)return;setBusy(true);setError('');try{const result=await submitForm('/admin/update/start',{commit:info.commit});setInfo(previous=>previous?{...previous,job:result.job}:previous)}catch(e){setError(e instanceof Error?e.message:String(e));await load(true)}finally{setBusy(false)}}
 const running=!!info&&['queued','checking','backing_up','building','restarting'].includes(info.job.state);
 const problem=error||fetchError||info?.check_error;
 const state=running?(fa?'در حال به‌روزرسانی':'Updating'):problem?(fa?'نیاز به بررسی':'Needs attention'):info?.available?(fa?'آپدیت جدید موجود است':'Update available'):info?(fa?'به‌روز است':'Up to date'):(fa?'در حال بررسی':'Checking');
 const jobLabels:Record<string,string>={queued:fa?'درخواست تأیید و برای VPS ثبت شد؛ در صف اجرا است.':'Update confirmed and sent to the VPS; queued for execution.',checking:fa?'VPS در حال بررسی نسخه است.':'VPS is checking the update.',backing_up:fa?'VPS در حال پشتیبان‌گیری دیتابیس است.':'VPS is backing up the database.',building:fa?'VPS در حال ساخت نسخه جدید است.':'VPS is building the update.',restarting:fa?'VPS در حال راه‌اندازی مجدد ربات است.':'VPS is restarting the bot.',completed:fa?'آپدیت VPS کامل شد.':'VPS update completed.',failed:fa?'آپدیت VPS ناموفق بود.':'VPS update failed.'};
 const hostMessages:Record<string,string>={worker_missing:fa?'اجراکننده آپدیت روی این VPS نصب یا فعال نشده است.':'The update worker has not been installed or enabled on this VPS.',worker_offline:fa?'ارتباط اجراکننده VPS قطع است.':'The VPS update worker is offline.',queue_not_writable:fa?'پنل به پوشه مشترک اجراکننده VPS دسترسی نوشتن ندارد.':'The panel cannot write to the shared VPS update directory.'};
 const confirmDisabled=busy||checking||running||!info?.available||!info?.commit||!!info?.check_error;
 return <section className="panel version-card" data-no-i18n="true" dir={fa?'rtl':'ltr'}>
  <div className="panel-head"><div className="settings-card-head"><PackageCheck size={21}/><h2>{fa?'نسخه':'Version'}</h2></div><span className={`badge ${problem?'yellow':info?.available?'blue':'green'}`} role="status">{state}</span></div>
  <div className="version-current"><strong dir="ltr">{info?`v${info.installed.version}`:'—'}</strong><span className="muted">{fa?'بیلد':'Build'} {info?.installed.build??'—'}</span></div>
  <div className="version-host"><Server size={15}/><span className={`badge ${info?.host_ready?'green':'yellow'}`}>{info?.host_ready?(fa?'متصل به VPS':'VPS connected'):(fa?'اجراکننده VPS آماده نیست':'VPS worker unavailable')}</span></div>
  {info?.available&&info.latest&&<p className="muted">{fa?'نسخه جدید:':'Latest:'} <b dir="ltr">v{info.latest.version} · {info.latest.build}</b></p>}
  {running&&<p role="status">{jobLabels[info!.job.state]}</p>}
  {problem&&!running&&<p className="settings-error" role="alert">{problem}</p>}
  <div className="settings-actions"><button type="button" className={`btn ${info?.available?'primary':''}`} onClick={()=>setOpen(true)} disabled={!info}><Download size={16}/>{fa?'جزئیات و آپدیت':'Details and update'}</button><button type="button" className="btn" onClick={()=>{setError('');void load(true)}} disabled={busy||checking||running} aria-label={fa?'بررسی دوباره':'Check again'}><RefreshCw size={16}/></button></div>
  {open&&createPortal(<AdminDialog label={fa?'به‌روزرسانی D BOT':'Update D BOT'} onClose={()=>setOpen(false)} busy={busy}><section className="modal-card version-dialog" data-no-i18n="true" dir={fa?'rtl':'ltr'}>
   <div className="modal-head"><h2>{fa?'به‌روزرسانی D BOT':'Update D BOT'}</h2><button type="button" className="btn" onClick={()=>setOpen(false)} disabled={busy} aria-label={fa?'بستن':'Close'}><X size={18}/></button></div>
   <p>{fa?'نسخه نصب‌شده:':'Installed:'} <b dir="ltr">v{info?.installed.version} · {info?.installed.build}</b></p>
   {info?.latest&&<><p>{fa?'آخرین نسخه:':'Latest:'} <b dir="ltr">v{info.latest.version} · {info.latest.build}</b></p><p className="version-notes">{info.latest.notes?.[fa?'fa':'en']}</p></>}
   <p className="muted">{fa?'با تأیید، درخواست به اجراکننده همین VPS ارسال می‌شود. ابتدا دیتابیس پشتیبان‌گیری، سپس ربات ساخته و راه‌اندازی مجدد می‌شود. پنل در زمان راه‌اندازی موقتاً قطع می‌شود.':'Confirmation sends the request to this VPS worker. It backs up the database, builds and restarts the bot. The panel is temporarily unavailable while restarting.'}</p>
   {!info?.host_ready&&!running&&<div className="settings-error" id="vps-update-help"><p>{hostMessages[info?.host?.reason||'worker_missing']||hostMessages.worker_offline}</p><p>{fa?'برای نصب یا بازیابی اتصال، یک‌بار روی همین VPS اجرا کنید؛ آپدیت‌های بعدی از همین پنل انجام می‌شوند.':'Run this once on this VPS to install or restore the connection. Future updates run from this panel.'}</p><code dir="ltr">{info?.host?.bootstrap_command||'sudo dbot update'}</code><button type="button" className="btn" disabled={checking} onClick={()=>void load(true)}>{fa?'بررسی اتصال VPS':'Check VPS connection'}</button></div>}
   {info?.job&&jobLabels[info.job.state]&&<p role="status">{jobLabels[info.job.state]}</p>}
   {running&&fetchError&&<p className="muted">{fa?'در انتظار برقراری دوباره پنل پس از راه‌اندازی VPS…':'Waiting for the panel to reconnect after VPS restart…'}</p>}
   {info?.job.backup&&<p className="muted version-notes">{fa?'پشتیبان:':'Backup:'} {info.job.backup}</p>}
   {(error||(!running&&fetchError)||info?.job.error||info?.check_error)&&<p className="settings-error" role="alert">{error||(!running&&fetchError)||info?.job.error||info?.check_error}</p>}
   {!info?.available&&!running&&<p className="muted">{fa?'آپدیت جدیدی برای نصب موجود نیست.':'No new update is available to install.'}</p>}
   <div className="settings-actions"><button type="button" className="btn primary" disabled={confirmDisabled} onClick={()=>void start()}><Download size={16}/>{busy?(fa?'در حال ثبت درخواست…':'Sending request…'):running?(fa?'آپدیت در حال اجرا است':'Update in progress'):(fa?'تأیید و آپدیت VPS':'Confirm and update VPS')}</button><button type="button" className="btn" onClick={()=>setOpen(false)} disabled={busy}>{fa?'بستن':'Close'}</button></div>
  </section></AdminDialog>,document.body)}
 </section>;
}
