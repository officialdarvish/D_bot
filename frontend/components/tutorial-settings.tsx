'use client';
import {useEffect,useState} from 'react';
import {fetchJson,submitForm} from '@/lib/api';
type App={id:string;platform:string;name:string;download_url:string;text:string;enabled:boolean};
export function TutorialSettings({show}:any){
 const [apps,setApps]=useState<App[]>([]),[enabled,setEnabled]=useState('1'),[rulesEnabled,setRulesEnabled]=useState('1'),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true);
 async function load(){setLoading(true);try{const d:any=await fetchJson('/admin/api/v2/tutorials');setApps(d.apps.map((row:App)=>({...row,enabled:row.enabled!==false})));setRulesEnabled(d.rules_button_enabled===false?'0':'1');setEnabled(d.enabled?'1':'0');setError('');}catch(e){setError(String(e));}finally{setLoading(false);}}
 useEffect(()=>{load();},[]);
 function field(index:number,key:keyof App,value:string|boolean){setApps(rows=>rows.map((row,i)=>i===index?{...row,[key]:value}:row));}
 async function save(){setBusy(true);try{await submitForm('/admin/settings/tutorials',{enabled,rules_button_enabled:rulesEnabled,apps_json:JSON.stringify(apps)});await load();show?.('آموزش‌ها ذخیره شدند.',true);}catch(e){show?.(String(e),false);}finally{setBusy(false);}}
 return <section className="card" dir="rtl" style={{padding:22,gridColumn:'1 / -1'}}>
 <h2>آموزش برنامه‌ها</h2><p className="muted">نام برنامه، لینک دانلود و متن آموزش را خودتان وارد کنید. مقادیر اولیه خالی هستند.</p>
 {error&&<p role="alert">{error}</p>}
 <label className="form-field"><span>دکمه آموزش در منوی ربات</span><select value={enabled} onChange={e=>setEnabled(e.target.value)}><option value="1">فعال</option><option value="0">غیرفعال</option></select></label>
 <label className="form-field"><span>دکمه قوانین در صفحه اصلی ربات</span><select value={rulesEnabled} onChange={e=>setRulesEnabled(e.target.value)}><option value="1">فعال</option><option value="0">غیرفعال</option></select></label>
 <p className="muted">غیرفعال کردن دکمه‌ها، متن‌ها را حذف نمی‌کند. نمایش قوانین از الزام پذیرش قوانین مستقل است.</p>
 {apps.map((row,i)=><fieldset key={row.id||i} style={{marginTop:18,padding:16,border:'1px solid #344256',borderRadius:12}}>
 <legend>برنامه {i+1}</legend><div className="form-grid">
 <label className="form-field"><span>نمایش دکمه این برنامه</span><select value={row.enabled?'1':'0'} onChange={e=>field(i,'enabled',e.target.value==='1')}><option value="1">فعال</option><option value="0">غیرفعال</option></select></label>
 <label className="form-field"><span>سیستم‌عامل</span><select value={row.platform} onChange={e=>field(i,'platform',e.target.value)}><option value="android">Android</option><option value="ios">iOS</option><option value="windows">Windows</option></select></label>
 <label className="form-field"><span>نام برنامه</span><input value={row.name} maxLength={60} onChange={e=>field(i,'name',e.target.value)}/></label>
 <label className="form-field"><span>لینک دانلود مستقیم</span><input dir="ltr" type="url" value={row.download_url} onChange={e=>field(i,'download_url',e.target.value)}/></label>
 </div><label className="form-field"><span>متن آموزش نصب و افزودن کانفیگ</span><textarea rows={6} maxLength={12000} value={row.text} onChange={e=>field(i,'text',e.target.value)}/></label>
 <button className="btn danger" onClick={()=>setApps(rows=>rows.filter((_,n)=>n!==i))}>حذف برنامه</button></fieldset>)}
 <div style={{display:'flex',gap:12,marginTop:18}}><button className="btn" disabled={loading||busy||apps.length>=60} onClick={()=>setApps(rows=>[...rows,{id:'',platform:'android',name:'',download_url:'',text:'',enabled:true}])}>افزودن برنامه</button><button className="btn primary" disabled={busy||loading||!!error} onClick={save}>ذخیره آموزش‌ها</button></div>
 </section>;
}
