'use client';
import {useEffect,useId,useRef,useState,type FormEvent} from 'react';
import {Save,Network,Link2,KeyRound,ShieldCheck,Webhook,RefreshCw} from 'lucide-react';
import {fetchJson,submitForm} from '@/lib/api';
import {publicWebPath} from '@/lib/web-path';
import {useUiLanguage} from '@/lib/ui-language';
export type BridgeSettingsInfo={ok:boolean;config:{enabled:boolean;url:string;bot_username:string;currency:string};key_saved:boolean;secret_saved:boolean;requires_toman_setup?:boolean};
export function BridgeSettings({onSaved,onAuthRequired,onBusyChange}:{onSaved?:()=>void;onAuthRequired?:()=>void;onBusyChange?:(busy:boolean)=>void}={}){
 const {language}=useUiLanguage(),fa=language==='fa',id=useId();
 const t=(en:string,ps:string)=>fa?ps:en;
 const pending=useRef(false);
 const [form,setForm]=useState({enabled:false,url:'',bot_username:'',currency:'IRT',key:'',secret:''}),[credentials,setCredentials]=useState({key:false,secret:false}),[loaded,setLoaded]=useState(false),[message,setMessage]=useState(''),[failed,setFailed]=useState(false),[busy,setBusy]=useState(false),[needsSetup,setNeedsSetup]=useState(false);
 function failure(e:unknown){const msg=e instanceof Error?e.message:String(e);if(msg==='AUTH_REQUIRED')onAuthRequired?.();setFailed(true);const messages:Record<string,string>={'AUTH_REQUIRED':'نشست ورود منقضی شده است؛ دوباره وارد شوید.','Bridge connection failed':'اتصال به بریج برقرار نشد؛ آدرس و وضعیت سرویس را بررسی کنید.','Bridge settings or capabilities are invalid; verify the companion configuration.':'تنظیمات یا قابلیت‌های بریج معتبر نیست؛ ارز و پشتیبانی محصولات دیجیتال را بررسی کنید.'};setMessage(fa?(messages[msg]||msg):msg)}
 async function load(signal?:AbortSignal){try{const r=await fetchJson<BridgeSettingsInfo>('/admin/api/v2/darvish-bridge',signal);if(signal?.aborted)return false;setForm(f=>({...f,...r.config}));setCredentials({key:r.key_saved,secret:r.secret_saved});setNeedsSetup(!!r.requires_toman_setup);setLoaded(true);setFailed(false);setMessage('');return true}catch(e){if(!signal?.aborted)failure(e);return false}}
 useEffect(()=>{const controller=new AbortController();void load(controller.signal);return()=>controller.abort()},[]);
 async function save(e:FormEvent){
  e.preventDefault();if(pending.current||!loaded)return;pending.current=true;setBusy(true);onBusyChange?.(true);setMessage('');setFailed(false);
  try{
   await submitForm('/admin/darvish-bridge/save',{...form,enabled:form.enabled?'1':'0'});
   setForm(f=>({...f,key:'',secret:''}));
   const refreshed=await load();
   setFailed(!refreshed);
   setMessage(refreshed?t('Settings saved. Connection and payment capability are checked when enabled.','تنظیمات ذخیره شد؛ اتصال و قابلیت پرداخت هنگام فعال‌سازی بررسی شدند.'):t('Settings saved, but the latest status could not be loaded. Reopen this form to verify.','تنظیمات ذخیره شد، اما دریافت وضعیت جدید ممکن نبود. برای بررسی، فرم را دوباره باز کنید.'));
   onSaved?.();
  }catch(e){failure(e)}finally{pending.current=false;setBusy(false);onBusyChange?.(false)}
 }
 const disabled=!loaded||busy;
 const webhook=typeof window!=='undefined'?window.location.origin+publicWebPath('/webhooks/darvish-bridge'):'';
 return <form className="bridge-connection-form" onSubmit={e=>void save(e)} aria-busy={disabled} data-no-i18n="true" dir={fa?'rtl':'ltr'}>
  <div className="bridge-intro"><span className="bridge-icon"><Network size={23}/></span><div><h3>{t('Payment connection','اتصال پرداخت')}</h3><p>{t('One connection for your bot and Mini App.','یک اتصال مشترک برای ربات و مینی‌اپ شما.')}</p></div><span className="badge">Bot + Mini App</span></div>
  <label className={`bridge-enable ${form.enabled?'is-enabled':''}`}><span><strong>{t('Enable Darvish Bridge','فعال‌سازی Darvish Bridge')}</strong><small>{t('Allow customers to pay through your Bridge connection.','امکان پرداخت مشتریان از طریق اتصال بریج را فعال کنید.')}</small></span><input type="checkbox" role="switch" checked={form.enabled} disabled={disabled} onChange={e=>setForm({...form,enabled:e.target.checked})}/></label>
  {needsSetup&&<p className="bridge-feedback is-error" role="status">{t('Revalidate and enable this connection for Toman payments. Existing invoices keep their original currency.','اتصال را برای پرداخت تومانی دوباره بررسی و فعال کنید. ارز فاکتورهای قبلی تغییر نمی‌کند.')}</p>}
  <div className="bridge-layout">
   <div className="bridge-fields">
    <fieldset className="bridge-group"><legend><Link2 size={16}/>{t('Connection details','اطلاعات اتصال')}</legend><div className="bridge-field-grid">
     <label className="form-field bridge-full" htmlFor={`${id}-url`}><span>{t('Bridge HTTPS URL','آدرس HTTPS بریج')}</span><input id={`${id}-url`} dir="ltr" disabled={disabled} type="url" autoComplete="off" required={form.enabled} value={form.url} placeholder="https://bridge.example.com" onChange={e=>setForm({...form,url:e.target.value})}/></label>
     <label className="form-field" htmlFor={`${id}-bot`}><span>{t('Bridge bot username','نام کاربری ربات بریج')}</span><input id={`${id}-bot`} dir="ltr" disabled={disabled} autoComplete="off" required={form.enabled} value={form.bot_username} placeholder="darvish_bridge_bot" onChange={e=>setForm({...form,bot_username:e.target.value})}/></label>
     <label className="form-field" htmlFor={`${id}-currency`}><span>{t('Payment currency','ارز پرداخت')}</span><select id={`${id}-currency`} dir="ltr" disabled={disabled} value="IRT" onChange={e=>setForm({...form,currency:e.target.value})}><option value="IRT">{t('Toman (IRT)','تومان (IRT)')}</option></select></label>
    </div></fieldset>
    <fieldset className="bridge-group"><legend><KeyRound size={16}/>{t('Credentials','کلیدهای اتصال')}</legend><div className="bridge-field-grid">
     {(['key','secret'] as const).map(key=><label className="form-field" key={key} htmlFor={`${id}-${key}`}><span className="bridge-field-label"><span>{key==='key'?'API key':'Webhook secret'}</span>{credentials[key]&&<small className="bridge-saved"><ShieldCheck size={12}/>{t('Saved','ذخیره‌شده')}</small>}</span><input id={`${id}-${key}`} dir="ltr" disabled={disabled} type="password" autoComplete="new-password" aria-describedby={`${id}-security-help`} required={form.enabled&&!credentials[key]} value={form[key]} placeholder={credentials[key]?t('Leave blank to keep saved value','برای حفظ مقدار ذخیره‌شده خالی بگذارید'):t('Enter credential','کلید اتصال را وارد کنید')} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>)}
    </div><p className="bridge-help" id={`${id}-security-help`}>{t('Saved credentials stay hidden. Enter a new value only when replacing them.','کلیدهای ذخیره‌شده نمایش داده نمی‌شوند. فقط برای جایگزینی، مقدار جدید وارد کنید.')}</p></fieldset>
   </div>
   <aside className="bridge-guide">
    <section className="bridge-webhook" aria-labelledby={`${id}-webhook`}><h3 id={`${id}-webhook`}><Webhook size={17}/>{t('Merchant webhook','وب‌هوک فروشنده')}</h3><p>{t('Use this URL in your Bridge merchant configuration.','این آدرس را در تنظیمات فروشنده بریج وارد کنید.')}</p><code dir="ltr">{webhook}</code></section>
    <section className="bridge-security-note"><ShieldCheck size={19}/><div><h3>{t('Encrypted credentials','کلیدهای رمزنگاری‌شده')}</h3><p>{t('Credentials are stored encrypted and shared by bot and Mini App payments.','کلیدها به‌صورت رمزنگاری‌شده ذخیره می‌شوند و برای پرداخت ربات و مینی‌اپ مشترک هستند.')}</p></div></section>
    <p className="bridge-help">{t('Payments use whole Toman amounts without USD, USDT or Rial conversion. Enabling validates Toman and digital product support.','پرداخت با مبلغ صحیح تومان و بدون تبدیل دلار، تتر یا ریال انجام می‌شود. هنگام فعال‌سازی، پشتیبانی تومان و محصولات دیجیتال بررسی می‌شوند.')}</p>
   </aside>
  </div>
  {message&&<p className={`bridge-feedback ${failed?'is-error':'is-success'}`} role={failed?'alert':'status'}>{message}</p>}
  <footer className="bridge-footer"><span>{!loaded?(failed?t('Connection settings unavailable.','تنظیمات اتصال در دسترس نیست.'):t('Loading connection settings…','در حال دریافت تنظیمات اتصال…')):t('Save to apply connection changes.','برای اعمال تغییرات اتصال، تنظیمات را ذخیره کنید.')}</span><div>{!loaded&&failed&&<button type="button" className="btn" onClick={()=>void load()}>{t('Retry','تلاش مجدد')}</button>}<button type="submit" className="btn primary" disabled={disabled}>{busy?<RefreshCw size={16} className="bridge-saving"/>:<Save size={16}/>} {busy?t('Checking…','در حال بررسی…'):t('Validate connection and save','بررسی اتصال و ذخیره')}</button></div></footer>
 </form>;
}
