'use client';
import {useId,useRef,useState} from 'react';
import {submitForm} from '@/lib/api';
import {useSettingsLanguage} from '@/lib/settings-language';
import {MessageSquare,PanelTop,Save,Eye,Braces} from 'lucide-react';
export function BotHomeSettings({map,show,setAuthRequired,section}:any){
 const {s,failure,language}=useSettingsLanguage();
 const fieldId=useId();
 const editor=useRef<HTMLTextAreaElement>(null);
 const [text,setText]=useState(String(map.welcome_text||''));
 const [savedText,setSavedText]=useState(String(map.welcome_text||''));
 const [visible,setVisible]=useState(map.button_panel_sales_enabled==='0'?'0':'1');
 const [busy,setBusy]=useState('');
 async function save(kind:'home'|'panel'){
  if(busy || (kind==='home' && (!text.trim() || text.length>4096)))return;
  setBusy(kind);
  try{
   if(kind==='home'){await submitForm('/admin/settings/home-message',{welcome_text:text});setSavedText(text.trim());setText(text.trim());}
   else await submitForm('/admin/settings/panel-sales-button',{enabled:visible});
   show?.(kind==='home'?s('Home message saved.','پیام صفحه اصلی ذخیره شد.'):s('Panel sales button saved.','وضعیت دکمه فروش پنل ذخیره شد.'),true);
  }catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired?.(true);show?.(failure(e),false);}
  finally{setBusy('');}
 }
 return <>
 {section!=='panel' && <section className="card home-message-card" data-no-i18n="true" dir={language==='fa'?'rtl':'ltr'} aria-labelledby={`${fieldId}-heading`}>
  <header className="home-message-heading"><span className="home-message-icon"><MessageSquare size={22}/></span><div><h2 id={`${fieldId}-heading`}>{s('Bot home message','پیام صفحه اصلی ربات')}</h2><p>{s('Welcome users with a message that matches your brand.','با پیامی متناسب با برندتان به کاربران خوشامد بگویید.')}</p></div><span className={`badge ${text.trim()===savedText.trim()?'green':'yellow'}`} role="status">{text.trim()===savedText.trim()?s('Saved','ذخیره‌شده'):s('Unsaved changes','تغییرات ذخیره‌نشده')}</span></header>
  <form onSubmit={event=>{event.preventDefault();void save('home')}} aria-busy={busy==='home'}>
   <div className="home-message-layout">
    <div className="home-message-editor">
     <div className="home-message-label"><label htmlFor={fieldId}>{s('Home message','متن صفحه اصلی')}</label><span dir="ltr">{text.length.toLocaleString(language==='fa'?'fa-IR':'en-US')} / 4,096</span></div>
     <textarea ref={editor} id={fieldId} rows={8} dir="auto" value={text} disabled={busy==='home'} required maxLength={4096} aria-describedby={`${fieldId}-help`} onChange={event=>setText(event.target.value)} placeholder={s('Write your welcome message…','پیام خوشامدگویی را بنویسید…')}/>
     <p id={`${fieldId}-help`} className="home-message-help">{s('Shown when users start the bot or return to its home screen.','هنگام شروع ربات یا بازگشت کاربران به صفحه اصلی نمایش داده می‌شود.')}</p>
     <div className="home-message-variables"><h3><Braces size={16}/>{s('Available variables','متغیرهای قابل استفاده')}</h3><p>{s('Select a variable to insert it at the cursor.','برای درج متغیر در محل نشانگر، روی آن بزنید.')}</p><div>{[
      ['{bot_name}',s('Bot name','نام ربات')],['{description}',s('Description','توضیحات')],['{support_username}',s('Support username','یوزرنیم پشتیبانی')]
     ].map(([token,label])=><button type="button" key={token} title={label} disabled={!!busy} onClick={()=>{const start=editor.current?.selectionStart??text.length,end=editor.current?.selectionEnd??start,next=text.slice(0,start)+token+text.slice(end);if(next.length>4096)return;setText(next);requestAnimationFrame(()=>{editor.current?.focus();editor.current?.setSelectionRange(start+token.length,start+token.length)})}}><code dir="ltr">{token}</code><span>{label}</span></button>)}</div></div>
    </div>
    <aside className="home-message-preview" aria-labelledby={`${fieldId}-preview`}><h3 id={`${fieldId}-preview`}><Eye size={16}/>{s('Text preview','پیش‌نمایش متن')}</h3><div className="home-message-bubble" dir="auto">{text.replaceAll('{bot_name}',String(map.bot_name||'D BOT')).replaceAll('{description}',String(map.admin_description||s('Your VPN shop','فروشگاه VPN شما'))).replaceAll('{support_username}',String(map.support_username||'@support'))||s('Your message preview appears here.','پیش‌نمایش پیام شما اینجا نمایش داده می‌شود.')}</div><p className="home-message-help">{s('Variables use your current settings. Telegram applies message formatting when it is sent.','متغیرها از تنظیمات فعلی خوانده می‌شوند. قالب‌بندی پیام هنگام ارسال در تلگرام اعمال می‌شود.')}</p></aside>
   </div>
   <footer className="home-message-footer"><p>{s('Changes take effect after saving.','تغییرات پس از ذخیره اعمال می‌شوند.')}</p><button className="btn primary" type="submit" disabled={!!busy||!text.trim()||text.length>4096||text.trim()===savedText.trim()}><Save size={17}/>{busy==='home'?s('Saving…','در حال ذخیره…'):s('Save home message','ذخیره پیام صفحه اصلی')}</button></footer>
  </form>
 </section>}
 {section!=='home' && <section className="card settings-card" data-no-i18n="true">
  <div className="settings-card-head"><PanelTop size={20}/><div><h2>{s('Reseller panel sales button','دکمه فروش پنل نمایندگی')}</h2><p className="muted">{s('Control its visibility in the customer menu.','نمایش این دکمه را در منوی کاربران کنترل کنید.')}</p></div></div>
  <label className="form-field"><span>{s('Show in customer menu','نمایش در منوی کاربران')}</span><select value={visible} onChange={e=>setVisible(e.target.value)}><option value="1">{s('Enabled','فعال')}</option><option value="0">{s('Disabled','غیرفعال')}</option></select></label>
  <p className="settings-help">{s('Panel sales must also be configured and enabled under PasarGuard Panel Sales. Hiding this button keeps existing purchased panels available.','فروش پنل باید در بخش فروش پنل پاسارگارد نیز پیکربندی و فعال باشد. مخفی‌کردن دکمه، دسترسی به پنل‌های خریداری‌شده را حذف نمی‌کند.')}</p>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy} onClick={()=>void save('panel')}><Save size={16}/>{busy==='panel'?s('Saving…','در حال ذخیره…'):s('Save button status','ذخیره وضعیت دکمه')}</button></div>
 </section>}</>;
}

