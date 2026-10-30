'use client';
import {useEffect,useState} from 'react';
import {fetchJson,submitForm} from '@/lib/api';
import {useSettingsLanguage} from '@/lib/settings-language';
import {BookOpen,Plus,Save,Trash2} from 'lucide-react';
type App={id:string;platform:string;name:string;download_url:string;text:string;enabled:boolean;video_file_id?:string};
export function TutorialSettings({show,setAuthRequired}:any){
 const {s,failure}=useSettingsLanguage();
 const [uploading,setUploading]=useState<number|null>(null);
 const [apps,setApps]=useState<App[]>([]),[enabled,setEnabled]=useState('1'),[rulesEnabled,setRulesEnabled]=useState('1'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
 async function load(){setLoading(true);try{const d:any=await fetchJson('/admin/api/v2/tutorials');setApps(d.apps.map((row:App)=>({...row,enabled:row.enabled!==false})));setRulesEnabled(d.rules_button_enabled===false?'0':'1');setEnabled(d.enabled?'1':'0');setError('');}catch(e){const msg=e instanceof Error?e.message:String(e);if(msg==='AUTH_REQUIRED')setAuthRequired?.(true);setError(msg);}finally{setLoading(false);}}
 useEffect(()=>{void load();},[]);
 function field(index:number,key:keyof App,value:string|boolean){setApps(rows=>rows.map((row,i)=>i===index?{...row,[key]:value}:row));}
 async function save(){setBusy(true);try{await submitForm('/admin/settings/tutorials',{enabled,rules_button_enabled:rulesEnabled,apps_json:JSON.stringify(apps)});await load();show?.(s('Tutorials saved.','آموزش‌ها ذخیره شدند.'),true);}catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired?.(true);show?.(failure(e),false);}finally{setBusy(false);}}
 async function uploadVideo(index:number,file:File){
  if(!file.name.toLowerCase().endsWith('.mp4')){show?.(s('Choose an MP4 video.','ویدیو MP4 انتخاب کنید.'),false);return;}
  if(!file.size||file.size>50*1024*1024){show?.(s('Video size must be between 1 byte and 50 MB.','حجم ویدیو باید بیشتر از صفر و حداکثر ۵۰ مگابایت باشد.'),false);return;}
  setBusy(true);setUploading(index);
  try{const result=await submitForm('/admin/settings/tutorials/video',{file});field(index,'video_file_id',result.video_file_id);show?.(s('Video uploaded. Save tutorials to attach it to this app.','ویدیو بارگذاری شد. برای ثبت آن در این برنامه، آموزش‌ها را ذخیره کنید.'),true);}
  catch(e){if(e instanceof Error&&e.message==='AUTH_REQUIRED')setAuthRequired?.(true);show?.(failure(e),false);}
  finally{setBusy(false);setUploading(null);}
 }
 const statuses=<><option value="1">{s('Enabled','فعال')}</option><option value="0">{s('Disabled','غیرفعال')}</option></>;
 return <section className="card settings-card settings-wide tutorial-settings" data-no-i18n="true">
 <div className="settings-card-head"><BookOpen size={20}/><div><h2>{s('App tutorials','آموزش برنامه‌ها')}</h2><p className="muted">{s('Manage app names, download links and connection guides.','نام برنامه‌ها، لینک دانلود و راهنمای اتصال را مدیریت کنید.')}</p></div></div>
 {error&&<p className="settings-error" role="alert">{failure(error)}</p>}
 <div className="settings-form-grid">
 <label className="form-field"><span>{s('Tutorial button in bot menu','دکمه آموزش در منوی ربات')}</span><select disabled={busy} value={enabled} onChange={e=>setEnabled(e.target.value)}>{statuses}</select></label>
 <label className="form-field"><span>{s('Rules button on bot home','دکمه قوانین در صفحه اصلی ربات')}</span><select disabled={busy} value={rulesEnabled} onChange={e=>setRulesEnabled(e.target.value)}>{statuses}</select></label>
 </div>
 <p className="settings-help">{s('Hiding a button keeps its content. Rules-button visibility is separate from requiring users to accept the rules.','مخفی‌کردن دکمه، محتوای آن را حذف نمی‌کند. نمایش دکمه قوانین از الزام پذیرش قوانین مستقل است.')}</p>
 {!loading&&!apps.length&&<div className="settings-empty">{s('No apps added yet. Add an app to create its tutorial.','هنوز برنامه‌ای اضافه نشده است. برای ساخت آموزش، یک برنامه اضافه کنید.')}</div>}
 {apps.map((row,i)=><fieldset key={row.id||i} className="settings-app">
 <legend>{s('App '+(i+1),'برنامه '+(i+1))}</legend><div className="settings-form-grid">
 <label className="form-field"><span>{s('App button visibility','نمایش دکمه این برنامه')}</span><select value={row.enabled?'1':'0'} onChange={e=>field(i,'enabled',e.target.value==='1')}>{statuses}</select></label>
 <label className="form-field"><span>{s('Operating system','سیستم‌عامل')}</span><select value={row.platform} onChange={e=>field(i,'platform',e.target.value)}><option value="android">{s('Android','اندروید')}</option><option value="ios">iOS</option><option value="windows">{s('Windows','ویندوز')}</option></select></label>
 <label className="form-field"><span>{s('App name','نام برنامه')}</span><input dir="auto" value={row.name} maxLength={60} onChange={e=>field(i,'name',e.target.value)}/></label>
 <label className="form-field"><span>{s('Direct download URL','لینک دانلود مستقیم')}</span><input dir="ltr" type="url" value={row.download_url} onChange={e=>field(i,'download_url',e.target.value)}/></label>
 </div><label className="form-field"><span>{s('Installation and connection guide','راهنمای نصب و اتصال')}</span><textarea dir="auto" rows={5} maxLength={12000} value={row.text} onChange={e=>field(i,'text',e.target.value)}/></label>
 <div className="settings-video"><label className="form-field"><span>{s('Tutorial video (MP4, up to 50 MB)','ویدیو آموزشی (MP4، حداکثر ۵۰ مگابایت)')}</span><span className="settings-video-picker"><span>{s('Choose video','انتخاب ویدیو')}</span><input aria-label={s('Choose tutorial video','انتخاب ویدیو آموزشی')} type="file" accept="video/mp4,.mp4" disabled={busy||loading} onChange={e=>{const file=e.target.files?.[0];if(file)void uploadVideo(i,file);e.target.value='';}}/></span></label><p className="settings-help" role="status">{uploading===i?s('Uploading video… Please wait.','در حال بارگذاری ویدیو… لطفاً صبر کنید.'):row.video_file_id?s('A video is attached. Selecting another video replaces it.','ویدیو پیوست شده است. انتخاب ویدیو جدید، قبلی را جایگزین می‌کند.'):s('Optional: upload a video, then save tutorials. Users receive it in Telegram with the guide and download link.','اختیاری: ویدیو را بارگذاری و سپس آموزش‌ها را ذخیره کنید. کاربر ویدیو را در تلگرام همراه راهنما و لینک دانلود دریافت می‌کند.')}</p>{row.video_file_id&&<button className="btn" disabled={busy} onClick={()=>field(i,'video_file_id','')}>{s('Remove video','حذف ویدیو')}</button>}</div>
 <button className="btn danger" disabled={busy} onClick={()=>setApps(rows=>rows.filter((_,n)=>n!==i))}><Trash2 size={15}/>{s('Remove app','حذف برنامه')}</button></fieldset>)}
 <div className="settings-actions"><button className="btn" disabled={loading||busy||apps.length>=60} onClick={()=>setApps(rows=>[...rows,{id:'',platform:'android',name:'',download_url:'',text:'',enabled:true}])}><Plus size={16}/>{s('Add app','افزودن برنامه')}</button><button className="btn primary" disabled={busy||loading||!!error} onClick={()=>void save()}><Save size={16}/>{uploading!==null?s('Uploading video…','در حال بارگذاری ویدیو…'):busy?s('Saving…','در حال ذخیره…'):s('Save tutorials','ذخیره آموزش‌ها')}</button></div>
 </section>;
}

