'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowRight,Gift,RefreshCw} from 'lucide-react';
import {errorMessage} from '@/lib/error-message';
import {canRequestTrial,trialServices,type TrialInfo,type TrialOperation} from '@/lib/miniapp-trial-state';

type API=<T,>(path:string,body?:unknown)=>Promise<T>;
export function MiniAppTrial({api,onBack,onService,onCompleted,refreshKey=0}:{api:API;onBack:()=>void;onService:(s:any)=>void;onCompleted?:()=>void;refreshKey?:number}){
 const [info,setInfo]=useState<TrialInfo|null>(null),[op,setOp]=useState<TrialOperation|null>(null);
 const [error,setError]=useState(''),[busy,setBusy]=useState(false);
 const key=useRef(''),requesting=useRef(false),version=useRef(0),mounted=useRef(true),completed=useRef(0),onCompletedRef=useRef(onCompleted);
 onCompletedRef.current=onCompleted;
 const running=op?.status==='queued'||op?.status==='processing';
 const load=useCallback(async()=>{
  const current=++version.current;
  try{
   const result=await api<TrialInfo>('/trial');
   if(!mounted.current||current!==version.current)return;
   setInfo(result);setOp(result.operation);setError('');
  }catch(e){if(mounted.current&&current===version.current){setInfo(null);setError(errorMessage(e,'دریافت وضعیت تست انجام نشد.','fa'));}}
 },[api]);
 useEffect(()=>{mounted.current=true;void load();return()=>{mounted.current=false;version.current++;}},[load,refreshKey]);
 useEffect(()=>{
  const refresh=()=>{if(document.visibilityState==='visible'&&!requesting.current)void load();};
  document.addEventListener('visibilitychange',refresh);
  const timer=setInterval(()=>{if(!running)refresh();},15000);
  return()=>{document.removeEventListener('visibilitychange',refresh);clearInterval(timer);};
 },[load,running]);
 useEffect(()=>{
  if(!running||!op)return;
  let live=true,inFlight=false;
  const timer=setInterval(async()=>{
   if(inFlight||document.visibilityState==='hidden')return;
   inFlight=true;
   const current=++version.current;
   try{
    const result=await api<TrialOperation>('/operations/'+op.id);
    if(!live||!mounted.current||current!==version.current)return;
    setOp(result);setError('');
   }catch(e){if(live&&mounted.current&&current===version.current)setError(errorMessage(e,'دریافت وضعیت تست انجام نشد.','fa'));}
   finally{inFlight=false;}
  },2000);
  return()=>{live=false;clearInterval(timer);};
 },[api,op?.id,running]);
 useEffect(()=>{
  if(!op||!['done','failed'].includes(op.status)||completed.current===op.id)return;
  completed.current=op.id;key.current='';
  void load();
  if(op.status==='done')onCompletedRef.current?.();
 },[op?.id,op?.status,load]);
 async function request(){
  if(requesting.current||running||!canRequestTrial(info,op))return;
  requesting.current=true;setBusy(true);setError('');
  const current=++version.current;
  if(!key.current)key.current=crypto.randomUUID();
  try{
   const result=await api<TrialOperation>('/trial',{key:key.current});
   if(mounted.current&&current===version.current)setOp(result);
  }catch(e){if(mounted.current&&current===version.current)setError(errorMessage(e,'ثبت درخواست تست انجام نشد.','fa'));}
  finally{requesting.current=false;if(mounted.current)setBusy(false);}
 }
 const services=trialServices(info,op);
 return <section className="ma-card ma-trial">
  <button className="ma-text" onClick={onBack}><ArrowRight size={18}/>بازگشت</button>
  <h1><Gift size={24}/> دریافت اکانت تست</h1>
  <p className="ma-muted">سهمیه، تنظیمات و کانفیگ‌های تست بین ربات و مینی‌اپ مشترک است.</p>
  {info&&<p>{info.volume_gb.toLocaleString('fa-IR')} گیگ · {info.duration_days.toLocaleString('fa-IR')} روز · {info.server_count.toLocaleString('fa-IR')} سرور</p>}
  {error&&<div role="alert" className="ma-error">{error}<button className="ma-text" disabled={busy} onClick={()=>void load()}>بررسی دوباره وضعیت</button></div>}
  {running?<p role="status"><RefreshCw className="ma-spin" size={18}/>در حال ساخت اکانت تست… پس از بازگشت به این صفحه، نتیجه همین درخواست نمایش داده می‌شود.</p>:<>
   {op?.result.message&&<p role={op.status==='failed'?'alert':'status'} className={op.status==='failed'?'ma-error':''}>{op.result.message}</p>}
   {info?.used&&op?.status!=='done'&&<p>شما قبلاً اکانت تست دریافت کرده‌اید.{services.length?' کانفیگ‌های موجود را از همین صفحه مشاهده کنید.':''}</p>}
   {services.map(service=><button key={service.id} className="ma-secondary" onClick={()=>onService({...service,source:'trial',source_label:'اکانت تست',checkout_delivery:true})}><Gift size={18}/>{service.server} · {service.username} · دریافت کانفیگ</button>)}
   {canRequestTrial(info,op)&&<button className="ma-primary" disabled={busy} onClick={()=>void request()}><Gift size={19}/>{busy?'در حال ثبت درخواست…':op?.status==='done'?'دریافت اکانت تست جدید':op?.status==='failed'?'تلاش مجدد برای دریافت تست':'دریافت اکانت تست رایگان'}</button>}
   {info&&!info.server_count&&<p className="ma-muted">تنظیمات اکانت تست هنوز توسط مدیر کامل نشده است.</p>}
   {!info&&!error&&<p>در حال دریافت تنظیمات…</p>}
  </>}
 </section>;
}
