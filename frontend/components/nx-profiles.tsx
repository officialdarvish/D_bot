'use client';
import { useMiniAppCopy } from '@/lib/miniapp-copy';
import {useState} from 'react';
type File={name:string;type:string;file_name:string;content:string};
export function NxProfiles({serviceId,api}:{serviceId:number;api:<T,>(path:string,body?:unknown)=>Promise<T>}){
 const copy = useMiniAppCopy();
 const [files,setFiles]=useState<File[]|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 const load=async()=>{setLoading(true);setError('');try{setFiles((await api<{files:File[]}>(`/services/${serviceId}/nx-configs`)).files)}catch(e){setError((e as Error).message)}finally{setLoading(false)}};
 function download(file:File){const u=URL.createObjectURL(new Blob([file.content],{type:'text/plain'}));const a=document.createElement('a');a.href=u;a.download=file.file_name;a.click();setTimeout(()=>URL.revokeObjectURL(u),10000)}
 return <div className="ma-card"><h2>{copy('profiles.text.58c5e37df8')}</h2><button className="ma-secondary" disabled={loading} onClick={()=>void load()}>{loading?copy('profiles.button.441def3dc4'):copy('profiles.button.46205fe1df')}</button>{error&&<p role="alert">{error}</p>}{files?.map((file,i)=><button key={i} className="ma-secondary" onClick={()=>download(file)}>{file.name} · {file.type}</button>)}{files?.length===0&&<p>{copy('profiles.text.37752495ce')}</p>}</div>
}
