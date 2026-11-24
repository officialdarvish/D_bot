'use client';
import { useMiniAppCopy } from '@/lib/miniapp-copy';
import {useId} from 'react';
import {ArrowUpRight,Check,Plus,Wifi} from 'lucide-react';
const fa=(n:number)=>new Intl.NumberFormat('fa-IR',{maximumFractionDigits:2}).format(n);
export function PanelWalletCard({balance,volume,available,suspended,disabled,onRecharge,theme='blue',holder='',reference=''}:{balance:number;volume:boolean;available:number;suspended:boolean;disabled?:boolean;onRecharge:()=>void;theme?:string;holder?:string;reference?:string}){
 const copy = useMiniAppCopy();
 const id=useId(),color=['red','black','green','purple','blue'].includes(theme)?theme:'blue';
 return <section className={'ma-panel-wallet ma-bank-wallet ma-bank-'+color} aria-labelledby={id} data-theme={color}>
  <div className="ma-bank-plastic"><div className="ma-bank-wallet-head"><div><span className="ma-bank-eyebrow">D BOT · PARTNER</span><h3 id={id}>{volume?copy('wallet.text.58bb61faf3'):copy('wallet.text.88a58e4354')}</h3></div><div className="ma-mastercard" role="img" aria-label="Mastercard"><span/><span/><small>mastercard</small></div></div>
  <div className="ma-bank-hardware" aria-hidden="true"><span className="ma-wallet-chip"/><Wifi size={23}/></div>
  <p className="ma-bank-balance-label">{volume?copy('wallet.text.3ca39923de'):copy('wallet.text.293640f9d7')}</p><div className="ma-panel-wallet-amount"><strong>{fa(volume?available/1024**3:balance)}</strong><span>{volume?copy('wallet.text.77bf229a4c'):copy('wallet.text.306eba5069')}</span></div>
  <div className="ma-bank-wallet-footer"><div><small>{copy('wallet.text.0fea302666')}</small><p dir="auto">{holder||'نماینده D Bot'}</p></div><div className="ma-bank-reference"><small>{copy('wallet.text.9dedd43916')}</small><p dir="ltr">#{reference||'—'}</p></div></div>
  </div><div className="ma-panel-wallet-status"><span className={suspended?'is-paused':''}/>{suspended?copy('wallet.text.6453d41f14'):volume?copy('wallet.text.089d37edd8'):copy('wallet.text.12234f1944')}</div>
  <button className="ma-panel-recharge" disabled={disabled} onClick={onRecharge} aria-label={copy('wallet.text.d4a4aa9e38')}><span className="ma-recharge-plus"><Plus size={22}/></span><span><b>{copy('wallet.button.d4a4aa9e38')}</b><small>{volume?copy('wallet.button.0a1fd4819d'):copy('wallet.button.6b129ef012')}</small></span><ArrowUpRight size={21}/></button>
  <p className="ma-panel-wallet-hint"><Check size={14}/>{suspended?copy('wallet.text.190c61eb14'):copy('wallet.text.e4f39edfa3')}</p>
 </section>
}
