'use client';
import {useEffect,useRef,useState} from 'react';
import {ArrowRight,BookOpen,ChevronDown,Download,PlayCircle,RefreshCw} from 'lucide-react';
type Tutorial={id:string;platform:string;name:string;download_url:string;text:string;video_url?:string};
type Content={rules:string;tutorials:Tutorial[]};
type API=<T,>(path:string,body?:unknown)=>Promise<T>;

function TutorialCard({item,api}:{item:Tutorial;api:API}){
 const [open,setOpen]=useState(false),[source,setSource]=useState(item.video_url),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const video=useRef<HTMLVideoElement>(null),resumeAt=useRef(0);
 useEffect(()=>{setSource(item.video_url);setError('')},[item.video_url]);
 async function reload(){
  if(busy)return;setBusy(true);setError('');resumeAt.current=video.current?.currentTime||0;
  try{const fresh=await api<Content>('/content'),url=fresh.tutorials.find(row=>row.id===item.id)?.video_url;if(!url)throw Error('ویدیوی این آموزش در دسترس نیست.');if(url===source)video.current?.load();else setSource(url)}
  catch(e){setError(e instanceof Error?e.message:'دریافت ویدیو انجام نشد. دوباره تلاش کنید.')}
  finally{setBusy(false)}
 }
 return <details className="ma-tutorial" onToggle={event=>{const expanded=event.currentTarget.open;setOpen(expanded);if(!expanded)video.current?.pause()}}>
  <summary><span className="ma-tutorial-icon" aria-hidden="true">{item.video_url?<PlayCircle size={23}/>:<BookOpen size={22}/>}</span><span className="ma-tutorial-title"><strong>{item.name}</strong><span><bdi className="ma-tutorial-platform">{item.platform}</bdi><small>{open?'بستن آموزش':'برای مشاهده آموزش بزنید'}</small></span></span><ChevronDown aria-hidden="true" size={20} className="ma-tutorial-chevron"/></summary>
  <div className="ma-tutorial-body">
   {item.text&&<p>{item.text}</p>}
   {source&&<video ref={video} controls playsInline preload={open?'metadata':'none'} src={source} aria-label={`ویدیوی آموزش ${item.name}`} onError={()=>setError('پخش ویدیو انجام نشد یا لینک آن منقضی شده است. ویدیو را دوباره بارگذاری کنید.')} onLoadedMetadata={()=>{if(resumeAt.current>0&&video.current&&Number.isFinite(video.current.duration)){video.current.currentTime=Math.min(resumeAt.current,video.current.duration);resumeAt.current=0}}}/>}
   {busy&&<p role="status">در حال دریافت ویدیو…</p>}
   {error&&<p className="ma-error" role="alert">{error}</p>}
   {item.video_url&&error&&<button type="button" className="ma-secondary" disabled={busy} onClick={()=>void reload()}><RefreshCw size={17} className={busy?'ma-spin':''}/>{busy?'در حال دریافت ویدیو…':'بارگذاری دوباره ویدیو'}</button>}
   {item.download_url&&<a className="ma-secondary ma-tutorial-download" href={item.download_url} target="_blank" rel="noopener noreferrer"><Download size={18}/>دانلود برنامه</a>}
  </div>
 </details>;
}
export function MiniAppContent({api,onBack,kind}:{api:API;onBack:()=>void;kind:'rules'|'tutorials'}){
 const [data,setData]=useState<Content|null>(null),[error,setError]=useState('');
 useEffect(()=>{let active=true;void api<Content>('/content').then(result=>{if(active){setData(result);setError('')}}).catch(e=>{if(active)setError(String(e.message||e))});return()=>{active=false}},[api]);
 return <section className="ma-card ma-content-page"><button type="button" className="ma-content-back" onClick={onBack}><ArrowRight size={17}/>بازگشت</button><h1>{kind==='rules'?'قوانین استفاده':'آموزش اتصال'}</h1>{kind==='tutorials'&&<p className="ma-tutorial-help">برنامه و سیستم‌عامل خود را انتخاب کنید و روی کارت آموزش بزنید.</p>}{error&&<p role="alert" className="ma-error">{error}</p>}{!data&&!error&&<p role="status">در حال دریافت…</p>}{data&&(kind==='rules'?<p className="ma-rules-text">{data.rules||'هنوز قانونی ثبت نشده است.'}</p>:data.tutorials.length?<div className="ma-tutorial-list">{data.tutorials.map(item=><TutorialCard key={item.id} item={item} api={api}/>)}</div>:<p>هنوز آموزشی ثبت نشده است.</p>)}</section>;
}
