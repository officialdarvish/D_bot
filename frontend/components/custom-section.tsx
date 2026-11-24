'use client';
import {useEffect,useMemo,useRef,useState} from 'react';
import {Bot,Save,RotateCcw,Plus,Trash2,Pencil,X,MessageSquareText,ChevronDown,Braces,Eye,Search,Palette,Smartphone} from 'lucide-react';
import {fetchJson,submitForm} from '@/lib/api';
import {useSettingsLanguage} from '@/lib/settings-language';
import {TutorialSettings} from '@/components/tutorial-settings';
import {DeliveryTemplates} from '@/components/delivery-templates';
import {MiniAppCustomization} from '@/components/miniapp-customization';
import {AdminDialog} from '@/components/admin-dialog';
import {BotTemplatePreview} from '@/components/bot-template-preview';
import {customJourney,journeys,type CustomItem} from '@/lib/custom-journeys';
const SECTION_LABELS: Record<string, string> = {
  'پرداخت، رسید و تأیید خرید': 'Payment, Receipt & Approval',
  'ساخت و تحویل سرویس': 'Service Creation & Delivery',
  'اطلاعات کانفیگ': 'Config Information',
  'انتخاب سرویس و پلن': 'Service & Plan Selection',
  'فرآیند خرید': 'Purchase Flow',
  'تمدید سرویس': 'Service Renewal',
  'مدیریت دستگاه و HWID': 'Device & HWID Management',
  'حذف کانفیگ': 'Config Removal',
  'مدیریت کانفیگ': 'Config Management',
  'مشاهده کانفیگ‌ها': 'View Configs',
  'کیف پول و رسید پرداخت': 'Wallet & Payment Receipt',
  'حساب کاربری': 'User Account',
  'ثبت و پیگیری تیکت': 'Create & Track Tickets',
  'رسید و شارژ نمایندگی': 'Reseller Receipt & Balance',
  'مدیریت یوزر نمایندگی': 'Reseller User Management',
  'پنل نمایندگی': 'Reseller Panel',
  'ساخت اکانت تست': 'Create Test Account',
  'گفتگوی خصوصی با مدیریت': 'Private Chat with Admin',
  'کارت و مشخصات سرویس': 'Service Card & Details',
  'پروفایل OpenVPN': 'OpenVPN Profile',
  'پیام نتیجه تمدید': 'Renewal Result Message',
  'ورود، قوانین و منوی اصلی': 'Entry, Rules & Main Menu',
  'دکمه‌های قابل مشاهده کاربر': 'User-visible Buttons',
  'هشدار حجم، زمان و غیرفعال شدن': 'Usage, Time & Disable Alerts',
  'اعلان انقضا و حذف': 'Expiration & Removal Notice',
  'دعوت، جایزه و پورسانت': 'Referral, Reward & Commission',
  'خطا و راهنمای ورودی': 'Input Errors & Guidance',
  'تعامل کاربر': 'User Interaction',
};

type Catalog={ok:boolean;items:CustomItem[];total:number;modified:number};
type Profile={id:string;name:string};
export function CustomSection({reloadKey,setAuthRequired,show}:{reloadKey:number;setAuthRequired:(v:boolean)=>void;show:(message:string,good?:boolean)=>void}){
 const {s,language,failure}=useSettingsLanguage(),fa=language==='fa';
 const [data,setData]=useState<Catalog|null>(null),[error,setError]=useState(''),[flow,setFlow]=useState('home'),[query,setQuery]=useState('');
 const [selected,setSelected]=useState<CustomItem|null>(null),[draft,setDraft]=useState(''),[enabled,setEnabled]=useState(true),[busy,setBusy]=useState(false),[revision,setRevision]=useState(0);
 const [profiles,setProfiles]=useState<Profile[]>([]),[profileId,setProfileId]=useState(''),[name,setName]=useState(''),[creating,setCreating]=useState(false),[visible,setVisible]=useState(30);
 const editor=useRef<HTMLTextAreaElement>(null);
 const [nestedDirty,setNestedDirty]=useState(false);
 const [surface,setSurface]=useState<'bot'|'miniapp'>('bot');
 useEffect(()=>{if(!nestedDirty)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[nestedDirty]);
 const label=(id:string)=>{const item=journeys.find(x=>x.id===id);return item?(fa?item.fa:item.en):id};
 function fail(e:unknown){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired(true);const known:Record<string,string>={'Remove unused delivery templates before applying this profile':s('Remove unused delivery templates before applying this profile.','برای اعمال این قالب، ابتدا قالب‌های تحویل سرویس بلااستفاده را حذف کنید.'),'You can save up to 8 templates':s('You can save up to 8 templates.','حداکثر ۸ قالب می‌توانید ذخیره کنید.')};const message=known[e instanceof Error?e.message:'']||failure(e);setError(message);show(message,false)}
 async function load(){const [catalog,templates]=await Promise.all([fetchJson<Catalog>('/api/admin/custom-texts'),fetchJson<{items:Profile[];ok:boolean}>('/admin/api/v2/custom-profiles')]);setData(catalog);setProfiles(templates.items);setError('')}
 useEffect(()=>{void load().catch(fail)},[reloadKey]);
 const entries=data?.items||[];
 const groups=useMemo(()=>journeys.map(j=>({...j,items:entries.filter(item=>customJourney(item)===j.id)})).filter(j=>j.items.length),[data]);
 const filtered=useMemo(()=>entries.filter(item=>customJourney(item)===flow&&(!query||`${item.current} ${item.default}`.toLowerCase().includes(query.toLowerCase()))),[data,flow,query]);
 const buttons=filtered.filter(item=>item.kind==='button').sort((a,b)=>Number(!!b.legacy_key)-Number(!!a.legacy_key)),messages=filtered.filter(item=>item.kind!=='button');
 const mainButtons=entries.filter(item=>item.kind==='button'&&/^button_.+_text$/.test(item.legacy_key||''));
 const currentSection=selected?label(customJourney(selected)):'';
 const sections=Array.from(new Set(messages.slice(0,visible).map(item=>item.section)));
 const dirty=!!selected&&(draft!==selected.current||(selected.enabled!=null&&enabled!==(selected.enabled!==false)));
 function choose(item:CustomItem){if(nestedDirty){show(s('Save your changes in this section first.','ابتدا تغییرات این بخش را ذخیره کن.'),false);return;}setSelected(item);setDraft(item.current);setEnabled(item.enabled!==false)}
 function close(){if(busy)return;if(dirty&&!window.confirm(s('Discard unsaved changes?','تغییرات ذخیره‌نشده کنار گذاشته شود؟')))return;setSelected(null)}
 function selectFlow(value:string){if(value===flow)return;if(nestedDirty&&!window.confirm(s('Discard unsaved changes in this section?','تغییرات ذخیره‌نشده این بخش کنار گذاشته شود؟')))return;setNestedDirty(false);setFlow(value);setQuery('');setVisible(30)}
 async function save(){
  if(!selected||busy)return;setBusy(true);
  try{await submitForm('/api/admin/custom-texts',{key:selected.key,value:draft,...(selected.enabled!=null?{enabled:enabled?'1':'0'}:{})});await load();setSelected(null);setRevision(v=>v+1);show(s('Text saved and applied to the bot.','متن ذخیره و در ربات اعمال شد.'),true)}catch(e){fail(e)}finally{setBusy(false)}
 }
 async function reset(){if(!selected||busy||!window.confirm(s('Restore this text to its default?','این متن به پیش‌فرض برگردد؟')))return;setBusy(true);try{await submitForm('/api/admin/custom-texts/reset',{key:selected.key});await load();setSelected(null);setRevision(v=>v+1);show(s('Default text restored.','متن پیش‌فرض بازگردانی شد.'),true)}catch(e){fail(e)}finally{setBusy(false)}}
 async function template(action:'create'|'apply'|'delete'){
  if(busy)return;
  if(nestedDirty&&action!=='apply'){const message=s('Save your changes in this section first.','ابتدا تغییرات این بخش را ذخیره کن.');show(message,false);return;}
  if(action==='apply'&&!window.confirm(s('Apply this template to all bot messages and buttons? Current texts and any unsaved changes will be replaced.','این قالب روی همه متن‌ها و دکمه‌های ربات اعمال شود؟ متن‌های فعلی و تغییرات ذخیره‌نشده جایگزین می‌شوند.')))return;
  if(action==='delete'&&!window.confirm(s('Delete this saved template? Applied bot texts will stay as they are.','این قالب ذخیره‌شده حذف شود؟ متن‌های اعمال‌شده ربات باقی می‌مانند.')))return;
  setBusy(true);try{await submitForm('/admin/api/v2/custom-profiles'+(action==='create'?'':'/'+action),action==='create'?{name}:{profile_id:profileId});await load();setNestedDirty(false);if(action==='create'){setName('');setCreating(false)}if(action==='delete')setProfileId('');setRevision(v=>v+1);show(action==='apply'?s('Template applied to the bot.','قالب در ربات اعمال شد.'):action==='delete'?s('Saved template deleted.','قالب ذخیره‌شده حذف شد.'):s('Template saved.','قالب ثبت شد.'),true)}catch(e){fail(e)}finally{setBusy(false)}
 }
 function insert(before:string,after=''){if(!selected)return;const start=editor.current?.selectionStart??draft.length,end=editor.current?.selectionEnd??start;setDraft(draft.slice(0,start)+before+draft.slice(start,end)+after+draft.slice(end));requestAnimationFrame(()=>{editor.current?.focus();editor.current?.setSelectionRange(start+before.length,end+before.length)})}
 function chooseSurface(next: typeof surface){
  if(next===surface)return;
  if(busy||(nestedDirty&&!window.confirm(s('Discard unsaved changes in this section?','تغییرات ذخیره‌نشدهٔ این بخش کنار گذاشته شوند؟'))))return;
  setNestedDirty(false);setSurface(next);
 }
 const surfaceMenu=<nav className="cj-miniapp-tabs" aria-label={s('Customize','سفارشی‌سازی')}>
  <button type="button" className={`btn ${surface==='bot'?'primary':''}`} aria-pressed={surface==='bot'} onClick={()=>chooseSurface('bot')}><Bot size={17}/>{s('Telegram bot','ربات تلگرام')}</button>
  <button type="button" className={`btn ${surface==='miniapp'?'primary':''}`} aria-pressed={surface==='miniapp'} onClick={()=>chooseSurface('miniapp')}><Smartphone size={17}/>{s('Mini App','مینی‌اپ')}</button>
 </nav>;
 if(surface==='miniapp')return <div className="custom-journeys" dir={fa?'rtl':'ltr'} data-no-i18n="true">{surfaceMenu}
  <MiniAppCustomization reloadKey={reloadKey} show={show} setAuthRequired={setAuthRequired} onDirtyChange={setNestedDirty}
   openSharedSection={section=>{setFlow(section);setQuery('');setVisible(30);setNestedDirty(false);setSurface('bot')}}/>
 </div>;
 if(!data)return <div className="custom-journeys" dir={fa?'rtl':'ltr'}>{surfaceMenu}<section className="panel" data-no-i18n="true"><p role={error?'alert':'status'}>{error||s('Loading bot templates…','در حال دریافت قالب‌های ربات…')}</p>{error&&<button className="btn" onClick={()=>void load().catch(fail)}>{s('Retry','تلاش دوباره')}</button>}</section></div>;
 return <div className="custom-journeys" dir={fa?'rtl':'ltr'} data-no-i18n="true">
  {surfaceMenu}
  <section className="panel cj-heading">
   <span className="cj-bot-icon"><Bot size={25}/></span>
   <div><h2>{s('Design your bot','رباتت را طراحی کن')}</h2><p>{s('Choose a menu button, edit its messages, then save your own style.','دکمه منو را انتخاب کن، پیام‌هایش را تغییر بده و قالب خودت را بساز.')}</p></div>
  </section>
  {error&&<p role="alert" className="settings-error">{error}</p>}
  <section className="panel cj-templates">
   <div className="cj-section-head"><div><h3><Palette size={18}/>{s('Your bot templates','قالب‌های ربات شما')}</h3><p>{s('Keep up to 8 saved styles for your bot’s messages and buttons.','تا ۸ قالب از متن‌ها و دکمه‌های رباتت نگه دار.')}</p></div><span className="badge">{profiles.length} / 8</span></div>
   <div className="cj-template-actions">
    <label className="form-field"><span>{s('Saved template','قالب ذخیره‌شده')}</span><select value={profileId} disabled={busy} onChange={e=>setProfileId(e.target.value)}><option value="">{s('Choose a template','انتخاب قالب')}</option><option value="default">{s('Project default','پیش‌فرض ربات')}</option>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <button className="btn" disabled={busy||!profileId} onClick={()=>void template('apply')}>{s('Apply template','اعمال قالب')}</button>
    <button className="btn primary" disabled={busy||profiles.length>=8} onClick={()=>setCreating(v=>!v)}><Plus size={16}/>{s('Save as template','ذخیره به‌عنوان قالب')}</button>
    {profileId&&profileId!=='default'&&<button className="icon-btn cj-delete-template" disabled={busy} aria-label={s('Delete saved template','حذف قالب ذخیره‌شده')} onClick={()=>void template('delete')}><Trash2 size={17}/></button>}
   </div>
   <p className="cj-note">{s('Save each edit first. “Save as template” captures your saved texts, including delivery templates.','اول هر ویرایش را ذخیره کن؛ «ذخیره به‌عنوان قالب» متن‌های ثبت‌شده و قالب‌های تحویل را نگه می‌دارد.')}</p>
   {creating&&<form className="cj-new-template" onSubmit={e=>{e.preventDefault();void template('create')}}>
    <label className="form-field"><span>{s('Template name','نام قالب')}</span><input value={name} maxLength={80} required disabled={busy} onChange={e=>setName(e.target.value)} placeholder={s('For example: My shop','مثلاً: قالب فروشگاه من')}/></label>
    <button className="btn primary" disabled={busy||!name.trim()}><Save size={16}/>{s('Save current style','ذخیره قالب فعلی')}</button>
    <button className="btn" type="button" disabled={busy} onClick={()=>setCreating(false)}>{s('Cancel','انصراف')}</button>
   </form>}
  </section>
  <section className="panel cj-menu">
   <div className="cj-section-head"><div><h3><Bot size={18}/>{s('Bot menu preview','پیش‌نمایش منوی ربات')}</h3><p>{s('Tap a button to open its related messages below.','روی دکمه بزن تا پیام‌های مرتبطش در پایین نمایش داده شوند.')}</p></div></div>
   <div className="cj-keyboard">{mainButtons.map(item=><button type="button" key={item.key} aria-controls="custom-message-section" aria-pressed={customJourney(item)===flow} className={item.enabled===false?'is-hidden':''} onClick={()=>selectFlow(customJourney(item))}><span dir="auto">{item.current}</span>{item.enabled===false&&<small>{s('Hidden','مخفی')}</small>}</button>)}</div>
   <label className="form-field cj-flow-picker"><span>{s('All bot sections','همه بخش‌های ربات')}</span><select value={flow} onChange={e=>selectFlow(e.target.value)}>{groups.map(group=><option key={group.id} value={group.id}>{label(group.id)} ({group.items.length})</option>)}</select></label>
  </section>
  {(flow==='services'||flow==='trial')&&<DeliveryTemplates onDirtyChange={setNestedDirty} key={flow+revision} scope={flow==='trial'?'trial':'service'} reloadKey={reloadKey+revision} show={show} setAuthRequired={setAuthRequired}/>}
  <section className="panel cj-flow" id="custom-message-section" aria-label={label(flow)}>
   <header className="cj-section-head"><div><h2>{label(flow)}</h2><p>{s('Choose a button or message to edit. Your changes apply after saving.','دکمه یا پیام را برای ویرایش انتخاب کن؛ تغییرات بعد از ذخیره اعمال می‌شوند.')}</p></div><span className="badge">{filtered.length} {s('items','مورد')}</span></header>
   <label className="form-field cj-search"><span>{s('Find text in this section','پیدا کردن متن در این بخش')}</span><span className="cj-search-field"><Search size={17}/><input type="search" value={query} onChange={e=>{setQuery(e.target.value);setVisible(30)}} placeholder={s('Type part of the message…','بخشی از متن را بنویس…')}/></span></label>
   {buttons.length>0&&<div className="cj-flow-buttons"><h3>{s('Buttons in this section','دکمه‌های این بخش')}</h3><div className="cj-keyboard">{buttons.slice(0,visible).map(item=><button type="button" key={item.key} className={item.customized?'is-custom':''} onClick={()=>choose(item)}><span dir="auto">{item.current}</span><Pencil size={14}/></button>)}</div>{buttons.length>visible&&<button className="btn cj-more" onClick={()=>setVisible(v=>v+30)}>{s('Show more buttons','نمایش دکمه‌های بیشتر')}</button>}</div>}
   <div className="cj-message-groups">
    <h3><MessageSquareText size={18}/>{s('Messages in this section','پیام‌های این بخش')}</h3>
    {!messages.length&&<div className="cj-empty"><MessageSquareText size={24}/><p>{query?s('No messages match your search.','پیامی مطابق جست‌وجوی شما پیدا نشد.'):s('This section has no editable messages.','این بخش پیام قابل‌ویرایشی ندارد.')}</p>{query&&<button className="btn" onClick={()=>setQuery('')}>{s('Clear search','پاک‌کردن جست‌وجو')}</button>}</div>}
    {sections.map((section,index)=><details className="cj-message-group" key={flow+':'+section} open={!!query||index===0}>
     <summary><span>{fa?section:(SECTION_LABELS[section]||'Messages')}</span><span className="cj-group-meta">{messages.filter(item=>item.section===section).length}<ChevronDown size={16}/></span></summary>
     <div>{messages.slice(0,visible).filter(item=>item.section===section).map(item=><button className={`cj-message ${item.customized?'is-custom':''}`} type="button" key={item.key} onClick={()=>choose(item)}>
      {item.legacy_key==='welcome_text'&&<strong className="cj-message-name">{s('Bot home message','پیام صفحه اصلی ربات')}</strong>}
      {item.legacy_key==='rules_text'&&<strong className="cj-message-name">{s('Rules message','متن قوانین')}</strong>}
      <span className="cj-message-text" dir="auto"><BotTemplatePreview text={item.current}/></span>
      <span className="cj-message-footer"><span>{item.customized?s('Customized','شخصی‌سازی‌شده'):s('Default','پیش‌فرض')}</span><span><Pencil size={14}/>{s('Edit message','ویرایش پیام')}</span></span>
     </button>)}</div>
    </details>)}
    {messages.length>visible&&<button className="btn cj-more" onClick={()=>setVisible(v=>v+30)}>{s('Show more messages','نمایش پیام‌های بیشتر')}</button>}
   </div>
  </section>
  {flow==='tutorials'&&<div className="section-grid settings-grid cj-tutorials"><TutorialSettings onDirtyChange={setNestedDirty} key={revision} setAuthRequired={setAuthRequired} show={(message:string,ok?:boolean)=>{show(message,ok);if(ok)void load().catch(fail)}}/></div>}
  {selected&&<AdminDialog label={selected.kind==='button'?s('Edit button','ویرایش دکمه'):s('Edit message','ویرایش پیام')} onClose={close} busy={busy}>
   <section className="modal-card cj-editor" dir={fa?'rtl':'ltr'} data-no-i18n="true">
    <header className="modal-head"><div><span className="cj-editor-section">{currentSection}</span><h2>{selected.kind==='button'?s('Edit button','ویرایش دکمه'):s('Edit message','ویرایش پیام')}</h2></div><button className="icon-btn" disabled={busy} aria-label={s('Close','بستن')} onClick={close}><X size={19}/></button></header>
    <div className="cj-editor-grid">
     <form onSubmit={e=>{e.preventDefault();void save()}}>
      <label className="form-field cj-edit-field"><span>{s('Your text','متن شما')}</span><textarea ref={editor} rows={selected.kind==='button'?3:9} value={draft} dir="auto" disabled={busy} onChange={e=>setDraft(e.target.value)}/><small className={draft.length>(selected.kind==='button'?64:4096)?'is-over-limit':''}>{draft.length} / {selected.kind==='button'?64:4096}</small></label>
      {selected.kind!=='button'&&<div className="cj-format-tools"><button type="button" disabled={busy} onClick={()=>insert('<b>','</b>')}><b>{s('Bold','پررنگ')}</b></button><button type="button" disabled={busy} onClick={()=>insert('<i>','</i>')}><i>{s('Italic','مورب')}</i></button></div>}
      {!!selected.placeholders?.length&&<div className="cj-variables"><span>{s('Insert a variable','درج متغیر')}</span><div className="cj-format-tools">{selected.placeholders.map(p=><button type="button" key={p} disabled={busy} onClick={()=>insert('{'+p+'}')}><Braces size={13}/><code dir="ltr">{p}</code></button>)}</div><p className="muted cj-help">{s('The bot fills these with the user’s real details when sending.','ربات این متغیرها را هنگام ارسال با اطلاعات واقعی کاربر تکمیل می‌کند.')}</p></div>}
      {selected.enabled!=null&&<label className="cj-visibility"><input type="checkbox" checked={enabled} disabled={busy} onChange={e=>setEnabled(e.target.checked)}/>{s('Show this button','نمایش این دکمه')}</label>}
      <details className="cj-default"><summary>{s('See default text','دیدن متن پیش‌فرض')}</summary><pre dir="auto">{selected.default}</pre></details>
      <footer className="cj-editor-actions"><button className="btn primary" disabled={busy||!dirty||!draft.trim()||draft.length>(selected.kind==='button'?64:4096)}><Save size={16}/>{busy?s('Saving…','در حال ذخیره…'):s('Save and apply','ذخیره و اعمال')}</button><button className="btn" type="button" disabled={busy} onClick={()=>void reset()}><RotateCcw size={16}/>{s('Use default','بازگشت به پیش‌فرض')}</button></footer>
     </form>
     <aside className="cj-preview-panel"><h3><Eye size={17}/>{s('Live preview','پیش‌نمایش زنده')}</h3><div className={`cj-live-preview ${selected.kind==='button'?'cj-live-button':''}`} dir="auto">{selected.kind==='button'?(draft||s('Your button text','متن دکمه شما')):<BotTemplatePreview text={draft||s('Your text preview','پیش‌نمایش متن شما')}/>}</div><p>{s('Variables appear as placeholders in this preview.','متغیرها در این پیش‌نمایش به‌صورت جای‌نگهدار نمایش داده می‌شوند.')}</p></aside>
    </div>
   </section>
  </AdminDialog>}
 </div>;
}
