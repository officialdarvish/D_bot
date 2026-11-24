'use client';
import { useMiniAppCopy } from '@/lib/miniapp-copy';
import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowRight,Gift,RefreshCw} from 'lucide-react';
import {errorMessage} from '@/lib/error-message';
import {canRequestTrial,trialServices,type TrialInfo,type TrialOperation} from '@/lib/miniapp-trial-state';

type API=<T,>(path:string,body?:unknown)=>Promise<T>;
export function MiniAppTrial({api,onBack,onService,onCompleted,refreshKey=0}:{api:API;onBack:()=>void;onService:(s:any)=>void;onCompleted?:()=>void;refreshKey?:number}){
 const copy = useMiniAppCopy();
 const [serverId,setServerId]=useState<number>(0);
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
  }catch(e){if(mounted.current&&current===version.current){setInfo(null);setError(errorMessage(e,copy('trial.text.88809848e5'),'fa'));}}
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
   }catch(e){if(live&&mounted.current&&current===version.current)setError(errorMessage(e,copy('trial.text.88809848e5'),'fa'));}
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
   const result=await api<TrialOperation>('/trial',{key:key.current,server_id:serverId||info?.servers?.[0]?.id});
   if(mounted.current&&current===version.current)setOp(result);
  }catch(e){if(mounted.current&&current===version.current)setError(errorMessage(e,copy('trial.text.61e3ae3083'),'fa'));}
  finally{requesting.current=false;if(mounted.current)setBusy(false);}
 }
 const services=trialServices(info,op);
 return <section className="ma-card ma-trial">
  <button className="ma-text" onClick={onBack}><ArrowRight size={18}/>{copy('trial.button.back')}</button>
  <h1><Gift size={24}/> {copy('trial.text.trial')}</h1>
  <p className="ma-muted">{copy('trial.text.536f88c519')}</p>
  {info&&<p>{info.volume_gb.toLocaleString('fa-IR')} {copy('trial.text.21f6e6a1ec')} {info.duration_days.toLocaleString('fa-IR')} {copy('trial.text.511d69c1e1')} {info.server_count.toLocaleString('fa-IR')} {copy('trial.text.f019da3ec8')}</p>}
  {info&&info.servers&&info.servers.length>0&&<label>{copy('trial.text.989bdaf3a4')}<select disabled={busy||running} value={serverId||info.servers[0].id} onChange={e=>{setServerId(Number(e.target.value));key.current=''}}>{info.servers.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>}
  {error&&<div role="alert" className="ma-error">{error}<button className="ma-text" disabled={busy} onClick={()=>void load()}>{copy('trial.button.a20e1822c1')}</button></div>}
  {running?<p role="status"><RefreshCw className="ma-spin" size={18}/>{copy('trial.text.ca7830eb60')}</p>:<>
   {op?.result.message&&<p role={op.status==='failed'?'alert':'status'} className={op.status==='failed'?'ma-error':''}>{op.result.message}</p>}
   {info?.used&&op?.status!=='done'&&<p>{copy('trial.text.2957d8f92b')}{services.length?copy('trial.text.90ead8e7c6'):''}</p>}
   {services.map(service=><button key={service.id} className="ma-secondary" onClick={()=>onService({...service,source:'trial',source_label:copy('trial.text.default_service_name'),checkout_delivery:true})}><Gift size={18}/>{service.server} · {service.username} {copy('trial.button.e6c3bbdc76')}</button>)}
   {canRequestTrial(info,op)&&<button className="ma-primary" disabled={busy} onClick={()=>void request()}><Gift size={19}/>{busy?copy('trial.button.0a91e95e77'):op?.status==='done'?copy('trial.button.28d19a8a3c'):op?.status==='failed'?copy('trial.button.659e374fa9'):copy('trial.button.8118a52fd5')}</button>}
   {info&&!info.server_count&&<p className="ma-muted">{copy('trial.text.e7a4fb1f75')}</p>}
   {!info&&!error&&<p>{copy('trial.text.4711825cc9')}</p>}
  </>}
 </section>;
}
