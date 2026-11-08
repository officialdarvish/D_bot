'use client';
import {Check} from 'lucide-react';
export function MiniAppPurchaseSteps({current}:{current:number}){
 return <div className="ma-checkout-steps" aria-label="مراحل خرید">{['دسته‌بندی','انتخاب پلن','نام کانفیگ','پرداخت','بررسی','دریافت'].map((label,index)=><span key={label} className={index===current?'active':index<current?'done':''} aria-current={index===current?'step':undefined}><b>{index<current?<Check size={12}/>:new Intl.NumberFormat('fa-IR').format(index+1)}</b>{label}</span>)}</div>
}
