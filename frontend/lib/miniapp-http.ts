import {errorMessage} from './error-message';

/** Fixed, same-origin Mini App API. Never parse proxy/login HTML as JSON. */
export async function miniAppRequest<T>(path:string,auth:string,body?:unknown):Promise<T>{
 if(!auth)throw new Error('مینی‌اپ را از دکمه کنار کادر چت تلگرام باز کنید.');
 if(!path.startsWith('/')||path.startsWith('//')||/[#\\\r\n]/.test(path))throw new Error('مسیر درخواست مینی‌اپ معتبر نیست.');
 const multipart=typeof FormData!=='undefined'&&body instanceof FormData;
 let response:Response;
 try{
  response=await fetch('/api/miniapp'+path,{method:body===undefined?'GET':'POST',cache:'no-store',credentials:'omit',redirect:'manual',headers:{Accept:'application/json','X-Telegram-Init-Data':auth,...(body!==undefined&&!multipart?{'Content-Type':'application/json'}:{})},...(body===undefined?{}:{body:multipart?body as FormData:JSON.stringify(body)})});
 }catch{
  throw new Error('ارتباط با سرور انجام نشد. اتصال را بررسی کنید؛ پیش از پرداخت یا ارسال دوباره، وضعیت همان سفارش را ببینید.');
 }
 if(response.type==='opaqueredirect'||response.redirected||(response.status>=300&&response.status<400))throw new Error('مسیر API به صفحه دیگری هدایت شد. مینی‌اپ را دوباره از تلگرام باز کنید؛ اگر مشکل باقی ماند با پشتیبانی تماس بگیرید.');
 if(response.status===413)throw new Error('وب‌سرور حجم عکس رسید را نپذیرفت. عکس کم‌حجم‌تری انتخاب کنید یا از پشتیبانی بخواهید محدودیت آپلود وب‌سرور را بررسی کند.');
 let data:unknown;
 try{
  const type=response.headers.get('content-type')||'';
  if(type&&!/\bapplication\/(?:[\w.-]+\+)?json\b/i.test(type))throw new Error();
  data=JSON.parse(await response.text());
  if(!data||typeof data!=='object')throw new Error();
 }catch{
  throw new Error([502,503,504].includes(response.status)?'سرور یا ارتباط با تلگرام موقتاً پاسخ نداد. وضعیت همان سفارش را بررسی کنید؛ دوباره پرداخت نکنید.':'پاسخ سرور معتبر نیست. وضعیت همان سفارش را بررسی کنید؛ در صورت تکرار، مسیر API و تنظیمات وب‌سرور باید توسط پشتیبانی بررسی شود.');
 }
 if(!response.ok)throw new Error(errorMessage(data,'درخواست انجام نشد؛ وضعیت سفارش را بررسی و دوباره تلاش کنید.','fa'));
 return data as T;
}

export const RECEIPT_MAX_BYTES=8*1024**2;
export function validateReceipt(file:File){
 if(!file.size)throw new Error('فایل رسید خالی است. عکس دیگری انتخاب کنید.');
 if(file.size>RECEIPT_MAX_BYTES)throw new Error('حجم عکس رسید باید حداکثر ۸ مگابایت باشد.');
 if(file.type&&!['image/jpeg','image/png','image/webp'].includes(file.type.toLowerCase()))throw new Error('عکس رسید را با فرمت JPG، PNG یا WebP ارسال کنید.');
}

type API=<T,>(path:string,body?:unknown)=>Promise<T>;
/** Reconcile a lost upload response with a read, never by replaying the upload. */
export async function uploadMiniAppReceipt<T extends {receipt_uploaded?:boolean}>(api:API,path:string,statusPath:string,file:File):Promise<T>{
 validateReceipt(file);
 const form=new FormData();form.append('file',file);
 try{return await api<T>(path,form)}catch(error){
  try{const current=await api<T>(statusPath);if(current.receipt_uploaded===true)return current}catch{/* Keep the original error and selected receipt for a deliberate retry. */}
  throw error;
 }
}
