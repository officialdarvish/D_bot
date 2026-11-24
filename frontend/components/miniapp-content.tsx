'use client';
import { useMiniAppCopy } from '@/lib/miniapp-copy';
import {useEffect,useRef,useState} from 'react';
import {ArrowRight,BookOpen,ChevronDown,Download,PlayCircle,RefreshCw} from 'lucide-react';
type Tutorial={id:string;platform:string;name:string;download_url:string;text:string;video_url?:string};
type Content={rules:string;tutorials:Tutorial[]};
type API=<T,>(path:string,body?:unknown)=>Promise<T>;

function TutorialCard({item,api}:{item:Tutorial;api:API}){
 const copy = useMiniAppCopy();
 const [open,setOpen]=useState(false),[source,setSource]=useState(item.video_url),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const video=useRef<HTMLVideoElement>(null),resumeAt=useRef(0);
 useEffect(()=>{setSource(item.video_url);setError('')},[item.video_url]);
 async function reload(){
  if(busy)return;setBusy(true);setError('');resumeAt.current=video.current?.currentTime||0;
  try{const fresh=await api<Content>('/content'),url=fresh.tutorials.find(row=>row.id===item.id)?.video_url;if(!url)throw Error(copy('help.text.90221869d2'));if(url===source)video.current?.load();else setSource(url)}
  catch(e){setError(e instanceof Error?e.message:copy('help.text.video_error'))}
  finally{setBusy(false)}
 }
 return <details className="ma-tutorial" onToggle={event=>{const expanded=event.currentTarget.open;setOpen(expanded);if(!expanded)video.current?.pause()}}>
  <summary><span className="ma-tutorial-icon" aria-hidden="true">{item.video_url?<PlayCircle size={23}/>:<BookOpen size={22}/>}</span><span className="ma-tutorial-title"><strong>{item.name}</strong><span><bdi className="ma-tutorial-platform">{item.platform}</bdi><small>{open?copy('help.text.a1bb1cbdfc'):copy('help.text.8e08a7d497')}</small></span></span><ChevronDown aria-hidden="true" size={20} className="ma-tutorial-chevron"/></summary>
  <div className="ma-tutorial-body">
   {item.text&&<p>{item.text}</p>}
   {source&&<video ref={video} controls playsInline preload={open?'metadata':'none'} src={source} aria-label={copy('help.text.cebb52253f', {value1: item.name})} onError={()=>setError(copy('help.text.aff67f3159'))} onLoadedMetadata={()=>{if(resumeAt.current>0&&video.current&&Number.isFinite(video.current.duration)){video.current.currentTime=Math.min(resumeAt.current,video.current.duration);resumeAt.current=0}}}/>}
   {busy&&<p role="status">{copy('help.text.13bceef628')}</p>}
   {error&&<p className="ma-error" role="alert">{error}</p>}
   {item.video_url&&error&&<button type="button" className="ma-secondary" disabled={busy} onClick={()=>void reload()}><RefreshCw size={17} className={busy?'ma-spin':''}/>{busy?copy('help.button.13bceef628'):copy('help.button.ea3f149de0')}</button>}
   {item.download_url&&<a className="ma-secondary ma-tutorial-download" href={item.download_url} target="_blank" rel="noopener noreferrer"><Download size={18}/>{copy('help.button.91fe5f12db')}</a>}
  </div>
 </details>;
}
export function MiniAppContent({api,onBack,kind}:{api:API;onBack:()=>void;kind:'rules'|'tutorials'}){
 const copy = useMiniAppCopy();
 const [data,setData]=useState<Content|null>(null),[error,setError]=useState('');
 useEffect(()=>{let active=true;void api<Content>('/content').then(result=>{if(active){setData(result);setError('')}}).catch(e=>{if(active)setError(String(e.message||e))});return()=>{active=false}},[api]);
 return <section className="ma-card ma-content-page"><button type="button" className="ma-content-back" onClick={onBack}><ArrowRight size={17}/>{copy('help.button.back')}</button><h1>{kind==='rules'?copy('help.text.911de8f0e1'):copy('help.text.0d4a1426b3')}</h1>{kind==='tutorials'&&<p className="ma-tutorial-help">{copy('help.text.d92f15c1fa')}</p>}{error&&<p role="alert" className="ma-error">{error}</p>}{!data&&!error&&<p role="status">{copy('help.text.441def3dc4')}</p>}{data&&(kind==='rules'?<p className="ma-rules-text">{data.rules||copy('help.text.0e6959137a')}</p>:data.tutorials.length?<div className="ma-tutorial-list">{data.tutorials.map(item=><TutorialCard key={item.id} item={item} api={api}/>)}</div>:<p>{copy('help.text.4832e64bd2')}</p>)}</section>;
}
