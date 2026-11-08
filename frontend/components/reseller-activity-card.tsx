'use client';
import {ArrowUpRight,Clock3,Plus,RefreshCw,Trash2,Wallet,XCircle} from 'lucide-react';
import {useUiLanguage} from '@/lib/ui-language';
export type ResellerActivity={
 id:number;action:string;action_label?:string;username:string;service_id?:number|null;server_name?:string;created_at?:string;expires_at?:string;
 volume_bytes:number;requested_volume_bytes?:number;previous_volume_bytes?:number;duration_days?:number;released_bytes?:number;old_unused_bytes?:number;old_used_bytes?:number;
 added_bytes?:number;deducted_bytes?:number;quota_before_bytes?:number;quota_after_bytes?:number;quota_remaining_after_bytes?:number;quota_delta_bytes?:number;quota_snapshot_version?:number;
 service_total_before_bytes?:number;service_total_after_bytes?:number;status?:string;source?:string;request_id?:number|null;operation_id?:string;package_title?:string;
 legacy_quota_snapshot_unavailable?:boolean;error_type?:string;error_message?:string;failure_stage?:string;panel_cleanup_pending?:boolean;
};
export function ResellerActivityCard({activity:a}:{activity:ResellerActivity}){
 const {language}=useUiLanguage();const fa=language==='fa';const t=(en:string,faText:string)=>fa?faText:en;
 const num=(n:number)=>new Intl.NumberFormat(fa?'fa-IR':'en-US',{maximumFractionDigits:2}).format(n);
 const gb=(n:number|undefined)=>num(Number(n||0)/1024**3)+' '+t('GB','گیگ');
 const date=(value?:string)=>{if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?'—':d.toLocaleString(fa?'fa-IR':'en-GB',{dateStyle:'short',timeStyle:'short'})};
 const failed=a.status==='failed'||a.action.endsWith('_failed');const action=a.action.replace(/_failed$/,'');
 const deleted=action==='delete';const returned=Math.max(0,Number(a.released_bytes||0));const unused=Math.max(returned,Number(a.old_unused_bytes||0));
 const tone=failed?'red':deleted?(unused>0?'purple':'red'):action==='renew'?'yellow':action==='topup'?'green':action==='create'?'blue':action==='quota_adjustment'?(Number(a.quota_delta_bytes||0)<0?'red':'green'):'blue';
 const labels:Record<string,string>={create:t('Account created','ساخت اکانت'),renew:t('Service renewed','تمدید سرویس'),topup:t('Volume purchased','خرید حجم'),delete:unused>0?t('Deleted · unused volume','حذف با حجم باقی‌مانده'):t('Config deleted','حذف کانفیگ'),quota_adjustment:t('Quota adjusted','اصلاح سهمیه'),add_volume:t('Volume added','افزایش حجم'),add_days:t('Days added','افزایش روز')};
 const label=(labels[action]||a.action_label||action)+(failed?t(' · failed',' · ناموفق'):'');
 const descriptions:Record<string,string>={create:t('New configuration ready.','کانفیگ جدید ساخته شد.'),renew:t('New service cycle started.','دوره جدید سرویس آغاز شد.'),topup:t('Volume added to reseller balance.','حجم به سهمیه نماینده اضافه شد.'),delete:a.panel_cleanup_pending?t('Removed; panel cleanup queued.','حذف شد؛ پاک‌سازی پنل در صف است.'):returned>0?t('Unused volume returned.','حجم مصرف‌نشده برگشت داده شد.'):t('Configuration removed.','کانفیگ حذف شد.'),quota_adjustment:t('Balance updated by admin.','سهمیه توسط مدیر اصلاح شد.'),add_volume:t('Service quota increased.','حجم سرویس افزایش یافت.'),add_days:t('Service validity extended.','اعتبار سرویس افزایش یافت.')};
 const exact=!a.legacy_quota_snapshot_unavailable&&((action==='create'||action==='renew')&&!failed?Number(a.quota_snapshot_version||0)>=2:(a.source!=='backfill'||Number(a.quota_before_bytes||0)!==0||Number(a.quota_after_bytes||0)!==0||Number(a.quota_remaining_after_bytes||0)!==0));
 const volume=Number(a.requested_volume_bytes||a.volume_bytes||a.deducted_bytes||0);
 const metrics:[string,string][]=[];
 if(action==='add_days')metrics.push([t('Days added','روز افزوده'),num(Number(a.duration_days||0))+' '+t('days','روز')]);
 else if(action==='quota_adjustment')metrics.push([t('Quota change','تغییر سهمیه'),(Number(a.quota_delta_bytes||0)>0?'+':'')+gb(a.quota_delta_bytes)]);
 else metrics.push([action==='topup'?t('Purchased','حجم خریداری‌شده'):t('Volume','حجم'),gb(action==='topup'?Number(a.added_bytes||a.volume_bytes):volume)]);
 if(deleted&&unused>0)metrics.push([returned>0?t('Returned','حجم برگشتی'):t('Unused','حجم باقی‌مانده'),gb(returned||unused)]);
 else if(Number(a.duration_days||0)>0&&action!=='add_days')metrics.push([t('Duration','مدت'),num(Number(a.duration_days))+' '+t('days','روز')]);
 if(exact&&!failed)metrics.push([t('Balance after','مانده پس از عملیات'),gb(a.quota_remaining_after_bytes??a.quota_after_bytes)]);
 const details:[string,string][]=[[t('Activity ID','شناسه عملیات'),'RA-'+a.id]];
 if(a.service_id)details.push([t('Service ID','شناسه سرویس'),String(a.service_id)]);
 if(a.request_id)details.push([t('Request ID','شناسه درخواست'),String(a.request_id)]);
 if(exact){details.push([t('Balance before','مانده قبل'),gb(a.quota_before_bytes)],[t('Balance after','مانده بعد'),gb(a.quota_remaining_after_bytes??a.quota_after_bytes)]);}
 else details.push([t('Historical balance','مانده تاریخی'),t('Not recorded','ثبت نشده')]);
 for(const [value,en,faLabel] of [[a.old_used_bytes,'Previous usage','مصرف قبلی'],[a.old_unused_bytes,'Unused volume','حجم مصرف‌نشده'],[a.previous_volume_bytes,'Previous volume','حجم قبلی'],[a.released_bytes,'Returned volume','حجم برگشتی'],[a.added_bytes,'Quota added','افزوده به سهمیه'],[a.deducted_bytes,'Quota deducted','کسر از سهمیه'],[a.service_total_before_bytes,'Service volume before','حجم قبلی سرویس'],[a.service_total_after_bytes,'Service volume after','حجم جدید سرویس']] as const){if(Number(value||0)>0)details.push([t(en,faLabel),gb(value)]);}
 if(Number(a.duration_days||0)>0)details.push([t('Duration','مدت'),num(Number(a.duration_days))+' '+t('days','روز')]);
 if(Number(a.quota_delta_bytes||0)!==0)details.push([t('Net quota change','تغییر خالص سهمیه'),(Number(a.quota_delta_bytes)>0?'+':'')+gb(a.quota_delta_bytes)]);
 if(a.expires_at)details.push([t('Expires','انقضا'),date(a.expires_at)]);
 if(a.package_title)details.push([t('Package','بسته'),a.package_title]);
 if(a.source)details.push([t('Source','منبع'),a.source]);
 if(a.operation_id)details.push([t('Operation ID','شناسه پردازش'),a.operation_id]);
 if(a.failure_stage)details.push([t('Failure stage','مرحله خطا'),a.failure_stage]);
 const Icon=failed?XCircle:deleted?Trash2:action==='renew'?RefreshCw:action==='topup'?Wallet:action==='add_volume'?ArrowUpRight:Plus;
 return <article className={'reseller-event event-'+tone} data-action={a.action} data-tone={tone} data-no-i18n="true" dir={fa?'rtl':'ltr'}>
  <div className="reseller-event-header"><span className="reseller-event-icon"><Icon size={19}/></span><div className="reseller-event-heading"><span className="reseller-event-label">{label}</span><strong dir="auto">{a.username||'—'}</strong></div><time dateTime={a.created_at}><Clock3 size={12}/>{date(a.created_at)}</time></div>
  <p className="reseller-event-description">{failed?t('Operation failed; see details.','عملیات ناموفق بود؛ جزئیات را ببینید.'):descriptions[action]||t('Activity recorded.','عملیات ثبت شد.')}</p>
  <dl className="reseller-event-metrics">{metrics.map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
  <footer className="reseller-event-footer"><span>{a.server_name||'—'}</span><span dir="ltr">#RA-{a.id}</span><details><summary>{t('Details','جزئیات')}</summary><dl className="reseller-event-details">{details.map(([key,value])=><div key={key}><dt>{key}</dt><dd dir="auto">{value}</dd></div>)}</dl>{failed&&<p className="activity-order-error" dir="auto">{a.error_type||t('Error','خطا')}: {a.error_message||t('No error details recorded.','جزئیات خطا ثبت نشده است.')}</p>}</details></footer>
 </article>;
}
