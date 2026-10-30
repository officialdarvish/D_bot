'use client';
import {useEffect,useState} from 'react';
import {Copy,Check} from 'lucide-react';
export function paymentCardNumber(value:string){
 return value.replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-1776)).replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-1632)).replace(/[\s-]+/g,'');
}
export function MiniAppPaymentCard({card}:{card?:{number:string;owner:string}}){
 const [copied,setCopied]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(!copied)return;const timer=setTimeout(()=>setCopied(false),3000);return()=>clearTimeout(timer)},[copied]);
 if(!card?.number)return null;
 const number=paymentCardNumber(card.number),display=/^\d{16}$/.test(number)?number.match(/.{4}/g)!.join(' '):card.number;
 async function copy(){
  setError('');
  try{
   try{if(!navigator.clipboard?.writeText)throw Error();await navigator.clipboard.writeText(number)}
   catch{const input=document.createElement('textarea');input.value=number;input.style.position='fixed';input.style.opacity='0';input.dir='ltr';document.body.appendChild(input);input.select();let ok=false;try{ok=document.execCommand('copy')}finally{input.remove()}if(!ok)throw Error()}
   setCopied(true);
  }catch{setCopied(false);setError('کپی انجام نشد؛ شماره کارت را انتخاب و کپی کنید.')}
 }
 return <div className="ma-bank-card"><small>شماره کارت</small><button className="ma-card-number" type="button" dir="ltr" aria-label="کپی کامل شماره کارت" onClick={()=>void copy()}>{display}</button><span>{card.owner}</span><button className="ma-text" type="button" onClick={()=>void copy()}>{copied?<Check size={16}/>:<Copy size={16}/>} {copied?'شماره کارت کپی شد':'کپی شماره کارت'}</button>{copied&&<small role="status">شماره کارت کپی شد.</small>}{error&&<small className="ma-error" role="alert">{error}</small>}</div>
}
