'use client';
import {useState} from 'react';
import {submitForm} from '@/lib/api';
import {useSettingsLanguage} from '@/lib/settings-language';
import {MessageSquare,PanelTop,Save} from 'lucide-react';
export function BotHomeSettings({map,show,setAuthRequired}:any){
 const {s,failure}=useSettingsLanguage();
 const [text,setText]=useState(String(map.welcome_text||''));
 const [visible,setVisible]=useState(map.button_panel_sales_enabled==='0'?'0':'1');
 const [busy,setBusy]=useState('');
 async function save(kind:'home'|'panel'){
  setBusy(kind);
  try{
   if(kind==='home')await submitForm('/admin/settings/home-message',{welcome_text:text});
   else await submitForm('/admin/settings/panel-sales-button',{enabled:visible});
   show?.(kind==='home'?s('Home message saved.','پیام صفحه اصلی ذخیره شد.'):s('Panel sales button saved.','وضعیت دکمه فروش پنل ذخیره شد.'),true);
  }catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired?.(true);show?.(failure(e),false);}
  finally{setBusy('');}
 }
 return <>
 <section className="card settings-card settings-wide" data-no-i18n="true">
  <div className="settings-card-head"><MessageSquare size={20}/><div><h2>{s('Bot home message','پیام صفحه اصلی ربات')}</h2><p className="muted">{s('Shown when users start the bot or return to its home screen.','هنگام شروع ربات یا بازگشت کاربران به صفحه اصلی نمایش داده می‌شود.')}</p></div></div>
  <label className="form-field"><span>{s('Home message','متن صفحه اصلی')}</span><textarea rows={6} dir="auto" value={text} onChange={e=>setText(e.target.value)}/></label>
  <div className="settings-help"><span>{s('Available variables','متغیرهای قابل استفاده')}</span><div className="settings-variables">{['{bot_name}','{description}','{support_username}'].map(v=><code key={v} dir="ltr">{v}</code>)}</div></div>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy||!text.trim()} onClick={()=>void save('home')}><Save size={16}/>{busy==='home'?s('Saving…','در حال ذخیره…'):s('Save home message','ذخیره پیام صفحه اصلی')}</button></div>
 </section>
 <section className="card settings-card" data-no-i18n="true">
  <div className="settings-card-head"><PanelTop size={20}/><div><h2>{s('Reseller panel sales button','دکمه فروش پنل نمایندگی')}</h2><p className="muted">{s('Control its visibility in the customer menu.','نمایش این دکمه را در منوی کاربران کنترل کنید.')}</p></div></div>
  <label className="form-field"><span>{s('Show in customer menu','نمایش در منوی کاربران')}</span><select value={visible} onChange={e=>setVisible(e.target.value)}><option value="1">{s('Enabled','فعال')}</option><option value="0">{s('Disabled','غیرفعال')}</option></select></label>
  <p className="settings-help">{s('Panel sales must also be configured and enabled under PasarGuard Panel Sales. Hiding this button keeps existing purchased panels available.','فروش پنل باید در بخش فروش پنل پاسارگارد نیز پیکربندی و فعال باشد. مخفی‌کردن دکمه، دسترسی به پنل‌های خریداری‌شده را حذف نمی‌کند.')}</p>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy} onClick={()=>void save('panel')}><Save size={16}/>{busy==='panel'?s('Saving…','در حال ذخیره…'):s('Save button status','ذخیره وضعیت دکمه')}</button></div>
 </section></>;
}

