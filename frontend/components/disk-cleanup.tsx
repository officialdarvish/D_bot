'use client';
import {useState} from 'react';
import {fetchJson,submitForm} from '@/lib/api';
import {useSettingsLanguage} from '@/lib/settings-language';
export function DiskCleanup({setAuthRequired,onClean}:{setAuthRequired:(v:boolean)=>void;onClean:()=>void}){
 const {s}=useSettingsLanguage();const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function clean(){
  if(busy)return;setBusy(true);setMessage('');
  try{
   const preview=await fetchJson<{files:number;bytes:number}>('/admin/api/v2/disk-cleanup');
   if(!preview.files){setMessage(s('No disposable files older than 7 days.','فایل موقت قابل حذف با عمر بیش از ۷ روز وجود ندارد.'));return}
   const amount=(preview.bytes/1024**2).toFixed(2);
   if(!window.confirm(s(`Delete ${preview.files} temporary files (${amount} MB) older than 7 days? Database records, stored backups and encryption keys are preserved.`,`آیا ${preview.files} فایل موقت قدیمی‌تر از ۷ روز (${amount} مگابایت) حذف شود؟ اطلاعات دیتابیس، بکاپ‌های ذخیره‌شده و کلیدهای رمزنگاری حفظ می‌شوند.`)))return;
   const result=await submitForm('/admin/api/v2/disk-cleanup',{});
   const freed=(result.bytes/1024**2).toFixed(2);
   setMessage(s(`${result.files} temporary files removed · ${freed} MB removed${result.skipped?' · Some files were skipped.':''}`,`${result.files} فایل موقت حذف شد · ${freed} مگابایت حذف شد${result.skipped?' · برخی فایل‌ها حذف نشدند.':''}`));onClean();
  }catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired(true);setMessage(s('Cleanup could not be completed. Please try again.','پاک‌سازی کامل نشد؛ دوباره تلاش کنید.'))}finally{setBusy(false)}
 }
 return <div data-no-i18n="true" className="disk-cleanup"><button className="btn mini" disabled={busy} onClick={()=>void clean()}>{busy?s('Checking…','در حال بررسی…'):s('Clean Temporary Files','پاک‌سازی فایل‌های موقت')}</button><small className="muted">{s('Only D BOT temporary files older than 7 days. Database records are never deleted.','فقط فایل‌های موقت D Bot با عمر بیش از ۷ روز؛ هیچ رکوردی از دیتابیس حذف نمی‌شود.')}</small>{message&&<small role="status">{message}</small>}</div>
}
