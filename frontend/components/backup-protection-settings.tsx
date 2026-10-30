'use client';
import {useEffect,useState} from 'react';
import {Archive,Download,Save,ShieldCheck} from 'lucide-react';
import {fetchJson,submitForm} from '@/lib/api';
import {publicWebPath} from '@/lib/web-path';
import {useSettingsLanguage} from '@/lib/settings-language';

type Protection = {ok:boolean;settings:Record<string,string>;status:any};
type Mode = 'normal'|'private'|'aes';
export function BackupProtectionSettings({reloadKey=0,show,setAuthRequired,onSaved}: {
 reloadKey?:number;show:(text:string,good?:boolean)=>void;setAuthRequired:(value:boolean)=>void;onSaved?:(data:Protection)=>void;
}) {
 const {language,s,failure}=useSettingsLanguage();
 const [mode,setMode]=useState<Mode>('private'),[savedMode,setSavedMode]=useState<Mode>('private');
 const [configured,setConfigured]=useState(false),[password,setPassword]=useState(''),[confirm,setConfirm]=useState('');
 const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
 useEffect(()=>{
  let active=true;setLoading(true);
  fetchJson<Protection>('/admin/api/v2/backup/settings').then(data=>{
   if(!active)return;const value=(data.settings.backup_protection_mode||'private') as Mode;
   setMode(value);setSavedMode(value);setConfigured(data.settings.backup_aes_password_configured==='1');setError('');
  }).catch(err=>{if(!active)return;if(err instanceof Error&&err.message==='AUTH_REQUIRED')setAuthRequired(true);setError(err instanceof Error?err.message:String(err));}).finally(()=>{if(active)setLoading(false)});
  return()=>{active=false};
 },[reloadKey]);
 async function save(){
  if(mode==='aes'&&((!configured&&!password)||password&&password!==confirm)){
   show(s('Enter and confirm the AES password.','رمز AES و تکرار آن را وارد کنید.'),false);return;
  }
  setBusy(true);
  try{
   await submitForm('/admin/backup/protection',{mode,aes_password:password,aes_password_confirm:confirm});
   const data=await fetchJson<Protection>('/admin/api/v2/backup/settings');
   setSavedMode(data.settings.backup_protection_mode as Mode);setMode(data.settings.backup_protection_mode as Mode);
   setConfigured(data.settings.backup_aes_password_configured==='1');setPassword('');setConfirm('');onSaved?.(data);
   show(mode==='private'?s('Protection saved. Recovery key list sent to the backup destination.','حفاظت ذخیره شد و فهرست کلیدهای بازیابی به مقصد بکاپ ارسال شد.'):s('Backup protection saved.','حفاظت بکاپ ذخیره شد.'),true);
  }catch(err){if(err instanceof Error&&err.message==='AUTH_REQUIRED')setAuthRequired(true);show(failure(err),false)}finally{setBusy(false)}
 }
 return <section className="card backup-security-card settings-wide" data-no-i18n="true" dir={language==='fa'?'rtl':'ltr'}>
  <div className="panel-head"><h2><ShieldCheck size={18}/>{s('Backup Protection','حفاظت بکاپ')}</h2><span className={`badge ${savedMode==='normal'?'yellow':'green'}`}>{savedMode==='normal'?s('Unencrypted','بدون رمزنگاری'):'AES-256-GCM'}</span></div>
  {loading?<p className="muted">{s('Loading…','در حال بارگذاری…')}</p>:error?<p role="alert">{failure(error)}</p>:<>
   <label className="form-field"><span>{s('Backup mode','حالت بکاپ')}</span><select value={mode} disabled={busy} onChange={e=>{setMode(e.target.value as Mode);setPassword('');setConfirm('')}}>
    <option value="normal">{s('Normal — readable backup','عادی — بکاپ خوانا')}</option>
    <option value="private">{s('Private key — send recovery key list','کلید اختصاصی — ارسال فهرست کلیدها')}</option>
    <option value="aes">{s('AES — administrator password','AES — رمز انتخابی مدیر')}</option>
   </select></label>
   <p className={`backup-mode-note ${mode==='normal'||mode==='private'?'backup-mode-warning':''}`}>
    {mode==='normal'?s('No whole-file encryption. Anyone with the file can read and restore its data.','فایل رمزنگاری کامل ندارد؛ هرکس فایل را داشته باشد می‌تواند اطلاعات آن را بخواند و بازیابی کند.'):
     mode==='private'?s('Uses a private key. Saving sends all registered backup recovery keys to the configured destination; each sent backup also includes a separate key-list message. Anyone with both messages can restore it. Keep an offline copy.','با کلید اختصاصی رمزنگاری می‌شود. با ذخیره، همه کلیدهای بازیابی ثبت‌شده به مقصد تنظیم‌شده ارسال می‌شوند؛ هنگام ارسال هر بکاپ هم فهرست کلیدها در پیام جدا می‌آید. دارنده هر دو پیام می‌تواند بازیابی کند؛ یک نسخه آفلاین نگه دارید.'):
     s('AES-256-GCM with a password-derived key (scrypt). A new VPS needs only the original password and backup. Passwords are never sent with backups; keep yours in a safe place.','رمزنگاری AES-256-GCM با کلید مشتق‌شده از رمز (scrypt). روی VPS جدید فقط فایل بکاپ و رمز زمان ساخت آن لازم است. رمز همراه بکاپ ارسال نمی‌شود؛ آن را در جای امن نگه دارید.')}
   </p>
   {mode==='aes'&&<div className="form-grid compact-form">
    <label className="form-field"><span>{s('AES password','رمز AES')}</span><input type="password" dir="ltr" autoComplete="new-password" minLength={12} maxLength={256} value={password} onChange={e=>setPassword(e.target.value)} placeholder={configured?s('Configured — leave blank to keep','تنظیم شده — برای حفظ خالی بگذارید'):s('12–256 characters','۱۲ تا ۲۵۶ نویسه')} disabled={busy}/></label>
    <label className="form-field"><span>{s('Confirm password','تکرار رمز')}</span><input type="password" dir="ltr" autoComplete="new-password" maxLength={256} value={confirm} onChange={e=>setConfirm(e.target.value)} disabled={busy}/></label>
   </div>}
   <p className="muted">{s('Save before creating a backup. Mode changes affect new files only; keep previous keys/passwords for older backups.','پیش از ساخت بکاپ، ذخیره کنید. تغییر حالت فقط روی فایل‌های جدید اعمال می‌شود؛ کلیدها و رمزهای قبلی را برای بکاپ‌های قدیمی حفظ کنید.')}</p>
   <div className="card-actions"><button className="btn primary" disabled={busy} onClick={save}><Save size={15}/>{busy?s('Saving…','در حال ذخیره…'):s('Save Protection','ذخیره حفاظت')}</button><a className="btn" href={publicWebPath('/admin/backup/recovery-keys')}><Download size={15}/>{s('Download Key List','دانلود فهرست کلیدها')}</a><a className="btn" href={publicWebPath('/admin/backup')}><Archive size={15}/>{s('Backup & Restore','بکاپ و بازیابی')}</a></div>
  </>}
 </section>
}
