'use client';
import {useEffect,useState} from 'react';
type Content={rules:string;tutorials:{id:string;platform:string;name:string;download_url:string;text:string}[]};
export function MiniAppContent({api,onBack,kind}:{api:<T,>(path:string,body?:unknown)=>Promise<T>;onBack:()=>void;kind:'rules'|'tutorials'}){
 const [data,setData]=useState<Content|null>(null),[error,setError]=useState('');
 useEffect(()=>{void api<Content>('/content').then(setData).catch(e=>setError(String(e.message||e)))},[api]);
 return <section className="ma-card"><button className="ma-text" onClick={onBack}>بازگشت</button><h1>{kind==='rules'?'قوانین استفاده':'آموزش اتصال'}</h1>{error&&<p role="alert">{error}</p>}{!data&&!error&&<p>در حال دریافت…</p>}{data&&(kind==='rules'?<p style={{whiteSpace:'pre-wrap'}}>{data.rules||'هنوز قانونی ثبت نشده است.'}</p>:data.tutorials.length?data.tutorials.map(item=><details key={item.id}><summary>{item.name} · {item.platform}</summary><p style={{whiteSpace:'pre-wrap'}}>{item.text}</p>{item.download_url&&<a className="ma-secondary" href={item.download_url} target="_blank" rel="noreferrer">دانلود برنامه</a>}</details>):<p>هنوز آموزشی ثبت نشده است.</p>)}</section>;
}
