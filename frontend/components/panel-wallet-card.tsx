'use client';
import {useId} from 'react';
import {ArrowUpRight,Check,Plus,Wifi} from 'lucide-react';
const fa=(n:number)=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(n);
export function PanelWalletCard({balance,volume,available,suspended,disabled,onRecharge,theme='blue',holder='',reference=''}:{balance:number;volume:boolean;available:number;suspended:boolean;disabled?:boolean;onRecharge:()=>void;theme?:string;holder?:string;reference?:string}){
 const id=useId(),color=['red','black','green','purple','blue'].includes(theme)?theme:'blue';
 return <section className={'ma-panel-wallet ma-bank-wallet ma-bank-'+color} aria-labelledby={id} data-theme={color}>
  <div className="ma-bank-plastic"><div className="ma-bank-wallet-head"><div><span className="ma-bank-eyebrow">D BOT · PARTNER</span><h3 id={id}>{volume?'کارت اعتبار حجمی':'کیف پول پنل نمایندگی'}</h3></div><div className="ma-mastercard" role="img" aria-label="Mastercard"><span/><span/><small>mastercard</small></div></div>
  <div className="ma-bank-hardware" aria-hidden="true"><span className="ma-wallet-chip"/><Wifi size={23}/></div>
  <p className="ma-bank-balance-label">{volume?'حجم قابل ساخت':'موجودی قابل استفاده'}</p><div className="ma-panel-wallet-amount"><strong>{fa(volume?available/1024**3:balance)}</strong><span>{volume?'گیگابایت':'تومان'}</span></div>
  <div className="ma-bank-wallet-footer"><div><small>دارندهٔ کارت</small><p dir="auto">{holder||'نماینده D Bot'}</p></div><div className="ma-bank-reference"><small>شناسهٔ پنل</small><p dir="ltr">#{reference||'—'}</p></div></div>
  </div><div className="ma-panel-wallet-status"><span className={suspended?'is-paused':''}/>{suspended?'متوقف به‌علت اتمام اعتبار':volume?'اعتبار حجمی':'پرداخت بر اساس مصرف'}</div>
  <button className="ma-panel-recharge" disabled={disabled} onClick={onRecharge} aria-label="افزایش اعتبار کیف پول پنل نمایندگی"><span className="ma-recharge-plus"><Plus size={22}/></span><span><b>افزایش اعتبار کیف پول پنل نمایندگی</b><small>{volume?'افزایش حجم با تعرفه اختصاصی شما':'پرداخت امن با ارسال رسید'}</small></span><ArrowUpRight size={21}/></button>
  <p className="ma-panel-wallet-hint"><Check size={14}/>{suspended?'بعد از تأیید شارژ، فعال‌سازی خودکار پیگیری می‌شود.':'اعتبار این کارت برای خدمات پنل نمایندگی است.'}</p>
 </section>
}
