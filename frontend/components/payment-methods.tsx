'use client';
import {useEffect,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {Plus,CreditCard,Network,Settings,X} from 'lucide-react';
import {AdminDialog} from '@/components/admin-dialog';
import {BridgeSettings,type BridgeSettingsInfo} from '@/components/bridge-settings';
import {fetchJson} from '@/lib/api';
import {useUiLanguage} from '@/lib/ui-language';

export function PaymentMethods({addCard,accountCount,query,reloadKey,children,setAuthRequired}:{addCard:()=>void;accountCount:number;query:string;reloadKey:number;children:ReactNode;setAuthRequired:(v:boolean)=>void}){
 const {language}=useUiLanguage(),fa=language==='fa';
 const [busy,setBusy]=useState(false);
 const [screen,setScreen]=useState<'choose'|'bridge'|null>(null),[bridge,setBridge]=useState<BridgeSettingsInfo|null>(null),[error,setError]=useState('');
 async function load(){try{setBridge(await fetchJson<BridgeSettingsInfo>('/admin/api/v2/darvish-bridge'));setError('')}catch(e){const msg=(e as Error).message;if(msg==='AUTH_REQUIRED')setAuthRequired(true);setError(msg)}}
 useEffect(()=>{void load()},[reloadKey]);
 const configured=!!bridge?.config.url;
 const visible=configured&&`Darvish Bridge ${bridge?.config.url} ${bridge?.config.bot_username}`.toLowerCase().includes(query.toLowerCase());
 return <>
  <div className="filterbar"><button type="button" className="btn primary" onClick={()=>setScreen('choose')}><Plus size={16}/>{fa?'افزودن روش پرداخت':'Add Payment'}</button><span className="badge">{accountCount+(visible?1:0)} {fa?'روش پرداخت':'payment methods'}</span></div>
  {error&&<p className="settings-error" role="alert">{error}</p>}
  <div className="section-grid">
   {visible&&<section className="card entity-card bridge-payment-card" data-no-i18n="true" dir={fa?'rtl':'ltr'}><div className="panel-head"><div className="settings-card-head"><span className="bridge-icon"><Network size={22}/></span><h2>Darvish Bridge</h2></div><span className={`badge ${bridge?.config.enabled?'green':'yellow'}`}>{bridge?.config.enabled?(fa?'فعال':'Enabled'):(fa?'غیرفعال':'Disabled')}</span></div><div className="kvs"><div className="kv"><span>{fa?'آدرس بریج':'Bridge URL'}</span><b dir="ltr">{bridge?.config.url}</b></div><div className="kv"><span>{fa?'ربات بریج':'Bridge bot'}</span><b dir="ltr">@{bridge?.config.bot_username}</b></div><div className="kv"><span>{fa?'ارز پرداخت':'Currency'}</span><b>{bridge?.config.currency}</b></div></div><div className="card-actions"><button className="btn" type="button" onClick={()=>setScreen('bridge')}><Settings size={16}/>{fa?'پیکربندی و اتصال':'Configure connection'}</button></div></section>}
   {children}
   {!accountCount&&!visible&&<div className="settings-empty">{fa?'برای افزودن حساب بانکی یا Darvish Bridge روی + بزنید.':'Use + to add a bank account or Darvish Bridge.'}</div>}
  </div>
  {screen&&createPortal(<AdminDialog label={screen==='choose'?(fa?'انتخاب روش پرداخت':'Choose payment method'):'Darvish Bridge'} busy={busy} onClose={()=>{if(!busy)setScreen(null)}}><section className={`modal-card payment-method-dialog ${screen==='bridge'?'bridge-dialog':''}`}  data-no-i18n="true" dir={fa?'rtl':'ltr'}><div className="modal-head"><h2>{screen==='choose'?(fa?'افزودن روش پرداخت':'Add payment method'):'Darvish Bridge'}</h2><button type="button" className="icon-btn" disabled={busy} aria-label={fa?'بستن':'Close'} onClick={()=>setScreen(null)}><X size={18}/></button></div>{screen==='choose'?<div className="payment-method-choices"><button type="button" className="payment-method-choice" onClick={()=>{setScreen(null);addCard()}}><CreditCard size={26}/><strong>{fa?'کارت / حساب بانکی':'Bank card / account'}</strong><span>{fa?'ثبت کارت و مدیر بررسی رسید':'Add a card and receipt reviewer'}</span></button><button type="button" className="payment-method-choice" onClick={()=>setScreen('bridge')}><Network size={26}/><strong>Darvish Bridge</strong><span>{fa?'پیکربندی و اتصال درگاه واسط':'Configure and connect the bridge'}</span></button></div>:<BridgeSettings onBusyChange={setBusy} onSaved={()=>void load()} onAuthRequired={()=>setAuthRequired(true)}/>}</section></AdminDialog>,document.body)}
 </>;
}
