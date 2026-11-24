'use client';
import { useMiniAppCopy } from '@/lib/miniapp-copy';
import {Check} from 'lucide-react';
export function MiniAppPurchaseSteps({current}:{current:number}){
 const copy = useMiniAppCopy();
 return <div className="ma-checkout-steps" aria-label={copy('steps.text.b283bd7456')}>{[copy('steps.text.category'), copy('steps.text.plan'), copy('steps.text.name'), copy('steps.text.payment'), copy('steps.text.review'), copy('steps.text.delivery')].map((label,index)=><span key={index} className={index===current?'active':index<current?'done':''} aria-current={index===current?'step':undefined}><b>{index<current?<Check size={12}/>:new Intl.NumberFormat('fa-IR').format(index+1)}</b>{label}</span>)}</div>
}
