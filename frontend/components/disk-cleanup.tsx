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
   if(!preview.files){setMessage(s('No temporary files older than 7 days or temporary backups older than 24 hours.','فایل موقت بیش از ۷ روز یا بکاپ موقت بیش از ۲۴ ساعت وجود ندارد.'));return}
   const amount=(preview.bytes/1024**2).toFixed(2);
   if(!window.confirm(s(`Delete ${preview.files} temporary files (${amount} MB)? Temporary files must be older than 7 days; temporary backups older than 24 hours. Database records, stored backups and encryption keys are preserved.`,`آیا ${preview.files} فایل موقت (${amount} مگابایت) حذف شود؟ فایل عادی باید بیش از ۷ روز و بکاپ موقت بیش از ۲۴ ساعت عمر داشته باشد. اطلاعات دیتابیس، بکاپ‌های ذخیره‌شده و کلیدهای رمزنگاری حفظ می‌شوند.`)))return;
   const result=await submitForm('/admin/api/v2/disk-cleanup',{});
   const freed=(result.bytes/1024**2).toFixed(2);
   setMessage(s(`${result.files} temporary files removed · ${freed} MB removed${result.skipped?' · Some files were skipped.':''}`,`${result.files} فایل موقت حذف شد · ${freed} مگابایت حذف شد${result.skipped?' · برخی فایل‌ها حذف نشدند.':''}`));onClean();
  }catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired(true);setMessage(s('Cleanup could not be completed. Please try again.','پاک‌سازی کامل نشد؛ دوباره تلاش کنید.'))}finally{setBusy(false)}
 }
 return <div data-no-i18n="true" className="disk-cleanup"><button title={s('Temporary backups older than 24 hours; other temporary files older than 7 days.','بکاپ موقت قدیمی‌تر از ۲۴ ساعت؛ سایر فایل‌های موقت قدیمی‌تر از ۷ روز.')} className="btn mini" disabled={busy} onClick={()=>void clean()}>{busy?s('Checking…','در حال بررسی…'):s('Clean Temporary Files','پاک‌سازی فایل‌های موقت')}</button>{message&&<small role="status">{message}</small>}</div>
}
