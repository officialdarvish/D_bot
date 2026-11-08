/** Convert API/validation failures into bounded, user-readable text.
 * Never stringify an unknown object: it may contain submitted secrets or a stack.
 */
export type ErrorLanguage = 'en' | 'fa';
const fields: Record<string, [string,string]> = {
 telegram_id:['Telegram numeric ID','آیدی عددی تلگرام'],total_gb:['Initial volume (GB)','حجم اولیه (گیگابایت)'],
 days:['Remaining days','روزهای اعتبار'],expires_at:['Expiry date','تاریخ انقضا'],
 wallet_adjustment_irt:['Wallet adjustment','تغییر موجودی کیف پول'],allowed_server_ids:['Allowed servers','سرورهای مجاز'],
 server_id:['Server','سرور'],username:['Username','نام کاربری'],password:['Password','رمز عبور'],
 full_name:['Full name','نام کامل'],billing_mode:['Financial system','سیستم مالی'],
 volume_gb:['Volume (GB)','حجم (گیگابایت)'],price_irt:['Price (Toman)','قیمت (تومان)'],
 duration_days:['Duration (days)','مدت (روز)'],file:['File','فایل'],inbound_ids:['Inbounds','اینباندها'],
};
export function errorMessage(value: unknown, fallback = 'The request could not be completed. Please try again.', language?: ErrorLanguage): string {
 const fa=(language || (typeof document!=='undefined' && document.documentElement.lang==='fa'?'fa':'en'))==='fa';
 const seen=new Set<object>();
 const clean=(text:string)=>text.trim().replace(/\[object [^\]]+\]/g,'').trim().slice(0,1200);
 function read(item:unknown,depth=0):string {
  if(depth>6 || item==null)return '';
  if(typeof item==='string')return clean(item);
  if(typeof item!=='object' || seen.has(item))return '';
  seen.add(item);
  if(item instanceof Error)return read(item.message,depth+1);
  if(Array.isArray(item))return Array.from(new Set(item.slice(0,5).map(x=>read(x,depth+1)).filter(Boolean))).join('\n');
  const row=item as Record<string,unknown>;
  if(Array.isArray(row.loc) && (typeof row.msg==='string'||typeof row.type==='string')){
   const loc=row.loc.filter(x=>typeof x==='string'&&!['body','query','path','header','cookie'].includes(x));
   const name=String(loc[loc.length-1]||'');
   const label=fields[name]?.[fa?1:0] || name.replace(/_/g,' ');
   const kind=String(row.type||'');
   let message='';
   if(kind==='missing')message=fa?'این فیلد الزامی است.':'This field is required.';
   else if(/int_(?:parsing|type|from_float)/.test(kind))message=fa?'عدد صحیح وارد کنید.':'Enter a whole number.';
   else if(/(?:float|decimal)_(?:parsing|type)|finite_number/.test(kind))message=fa?'عدد معتبر وارد کنید.':'Enter a valid number.';
   else if(/greater_than/.test(kind))message=fa?'مقدار از حداقل مجاز کمتر است.':'The value is below the allowed minimum.';
   else if(/less_than/.test(kind))message=fa?'مقدار از حداکثر مجاز بیشتر است.':'The value exceeds the allowed maximum.';
   else if(kind==='string_type')message=fa?'متن وارد کنید.':'Enter text.';
   else if(kind==='string_too_short')message=fa?'متن بیش از حد کوتاه است.':'The text is too short.';
   else if(kind==='string_too_long')message=fa?'متن بیش از حد طولانی است.':'The text is too long.';
   else message=typeof row.msg==='string'?clean(row.msg):(fa?'مقدار واردشده معتبر نیست.':'Invalid value.');
   return label?`${label}: ${message}`:message;
  }
  for(const key of ['message','detail','errors','error']){
   const result=read(row[key],depth+1);
   if(result)return result;
  }
  return '';
 }
 return read(value).slice(0,1800)||clean(fallback)||(fa?'درخواست انجام نشد؛ دوباره تلاش کنید.':'The request could not be completed.');
}
