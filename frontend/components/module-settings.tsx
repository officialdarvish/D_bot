'use client';
import {useEffect,useState} from 'react';
import {Blocks,Users,ShieldCheck,FlaskConical,Wallet,BookOpen,Network,Save,LoaderCircle} from 'lucide-react';
import {fetchJson,submitForm} from '@/lib/api';
import {useUiLanguage} from '@/lib/ui-language';

export function ModuleSettings(){
 const {language}=useUiLanguage(),fa=language==='fa';
 const [values,setValues]=useState<Record<string,boolean>>({}),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false),[failed,setFailed]=useState(false);
 useEffect(()=>{let active=true;void fetchJson<{features:Record<string,boolean>}>('/admin/api/v2/capabilities').then(r=>{if(active){setValues(r.features);setLoaded(true)}}).catch(e=>{if(active){setMessage(e.message);setFailed(true)}});return()=>{active=false}},[]);
 const modules=[
  {key:'resellers',icon:Users,title:fa?'نمایندگی':'Resellers',description:fa?'منوها و خدمات فروش نمایندگی':'Reseller menus and sales services'},
  {key:'openvpn',icon:ShieldCheck,title:'OpenVPN',description:fa?'پروفایل‌ها و ابزارهای اتصال میکروتیک':'MikroTik profiles and connection tools'},
  {key:'trials',icon:FlaskConical,title:fa?'اکانت تست':'Trial accounts',description:fa?'دریافت اکانت تست از سرورهای منتخب':'Trial accounts from selected servers'},
  {key:'wallet',icon:Wallet,title:fa?'کیف پول':'Wallet',description:fa?'شارژ حساب و پرداخت با موجودی':'Account funding and balance payments'},
  {key:'tutorials',icon:BookOpen,title:fa?'آموزش':'Tutorials',description:fa?'نمایش آموزش‌های اتصال برای کاربران':'Connection guides for customers'},
  {key:'xray',icon:Network,title:'Xray',description:fa?'هسته اختیاری برای اتصال تلگرام':'Optional core for Telegram connectivity'},
 ];
 async function save(){setBusy(true);setFailed(false);setMessage('');try{await submitForm('/admin/modules/save',Object.fromEntries(modules.map(({key})=>[key,values[key]?'1':'0'])));window.location.reload()}catch(e){setFailed(true);setMessage((e as Error).message)}finally{setBusy(false)}}
 return <section className="card settings-wide module-settings" aria-busy={busy||!loaded}>
  <div className="panel-head"><div className="settings-card-head"><Blocks size={21}/><div><h2>{fa?'ماژول‌های ربات':'Bot modules'}</h2><p className="muted">{fa?'قابلیت‌های مورد نیاز ربات و مینی‌اپ را انتخاب کنید.':'Choose the features available in your bot and Mini App.'}</p></div></div><span className="badge blue">{modules.filter(m=>values[m.key]).length} / {modules.length}</span></div>
  <div className="module-grid">{modules.map(({key,icon:Icon,title,description})=><label key={key} className={`module-option ${values[key]?'is-enabled':''}`}><span className="module-icon"><Icon size={20}/></span><span className="module-copy"><strong>{title}</strong><small>{description}</small></span><input type="checkbox" role="switch" aria-label={title} checked={!!values[key]} disabled={!loaded||busy} onChange={e=>setValues(v=>({...v,[key]:e.target.checked}))}/></label>)}</div>
  <p className="settings-help">{fa?'با اضافه‌شدن سرور میکروتیک، ابزارهای OpenVPN به‌صورت خودکار در دسترس قرار می‌گیرند.':'Adding a MikroTik server automatically makes OpenVPN tools available.'}</p>
  <div className="settings-actions"><button type="button" className="btn primary" disabled={busy||!loaded} onClick={()=>void save()}>{busy?<LoaderCircle size={16} className="spin"/>:<Save size={16}/>} {fa?'ذخیره تغییرات':'Save changes'}</button>{message&&<p className={failed?'settings-error':'muted'} role={failed?'alert':'status'}>{message}</p>}</div>
 </section>;
}
