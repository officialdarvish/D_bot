'use client';
import { useMiniAppCopy } from '@/lib/miniapp-copy';
import {useEffect,useState} from 'react';
import {Copy,Check} from 'lucide-react';
export function paymentCardNumber(value:string){
 return value.replace(/[۰-۹]/g,c=>String(c.charCodeAt(0)-1776)).replace(/[٠-٩]/g,c=>String(c.charCodeAt(0)-1632)).replace(/[\s-]+/g,'');
}
export function MiniAppPaymentCard({card}:{card?:{number:string;owner:string}}){
 const copy = useMiniAppCopy();
 const [copied,setCopied]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(!copied)return;const timer=setTimeout(()=>setCopied(false),3000);return()=>clearTimeout(timer)},[copied]);
 if(!card?.number)return null;
 const number=paymentCardNumber(card.number),display=/^\d{16}$/.test(number)?number.match(/.{4}/g)!.join(' '):card.number;
 async function copyCardNumber(){
  setError('');
  try{
   try{if(!navigator.clipboard?.writeText)throw Error();await navigator.clipboard.writeText(number)}
   catch{const input=document.createElement('textarea');input.value=number;input.style.position='fixed';input.style.opacity='0';input.dir='ltr';document.body.appendChild(input);input.select();let ok=false;try{ok=document.execCommand('copy')}finally{input.remove()}if(!ok)throw Error()}
   setCopied(true);
  }catch{setCopied(false);setError(copy('payment.text.ea745c88c5'))}
 }
 return <div className="ma-bank-card"><small>{copy('payment.text.a6d8db079a')}</small><button className="ma-card-number" type="button" dir="ltr" aria-label={copy('payment.text.8f9fb08ac3')} onClick={()=>void copyCardNumber()}>{display}</button><span>{card.owner}</span><button className="ma-text" type="button" onClick={()=>void copyCardNumber()}>{copied?<Check size={16}/>:<Copy size={16}/>} {copied?copy('payment.button.09b9d4ce77'):copy('payment.button.ecb5f66900')}</button>{copied&&<small role="status">{copy('payment.text.5fdeb43664')}</small>}{error&&<small className="ma-error" role="alert">{error}</small>}</div>
}
