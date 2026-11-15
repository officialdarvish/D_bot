'use client';
import {useEffect,useState} from 'react';
import {Users} from 'lucide-react';
import {fetchJson} from '@/lib/api';
import {useUiLanguage} from '@/lib/ui-language';
export function InstallationCount(){
 const {language}=useUiLanguage();
 const fa=language==='fa';
 const [count,setCount]=useState<number|null>(null);
 useEffect(()=>{let alive=true;const update=()=>void fetchJson<{count:number|null}>('/admin/api/v2/installation-count').then(r=>{if(alive)setCount(r.count)}).catch(()=>{if(alive)setCount(null)});update();const timer=setInterval(update,60000);return()=>{alive=false;clearInterval(timer)}},[]);
 return <div className="installation-count" data-no-i18n="true" title={fa?'نصب‌هایی که در ۱۵ دقیقه اخیر به شمارنده متصل بوده‌اند؛ بروزرسانی هر دقیقه':'Installations reporting within the last 15 minutes; refreshed every minute'}><Users size={18}/><span>{fa?'نصب‌های فعال D BOT':'Active D BOT installs'}</span><strong>{count===null?'—':count.toLocaleString('en-US')}</strong></div>;
}
