'use client';
import {useUiLanguage, translateUiText} from './ui-language';
export function useSettingsLanguage() {
 const {language}=useUiLanguage();
 const s=(en:string,fa:string)=>language==='fa'?fa:en;
 function failure(error:unknown) {
  const message=error instanceof Error?error.message:String(error);
  const known:Record<string,[string,string]>={
   'ویدیو باید با فرمت MP4 باشد.':['The video must be an MP4 file.','ویدیو باید با فرمت MP4 باشد.'],
   'حجم ویدیو باید حداکثر ۵۰ مگابایت باشد.':['The video must be no larger than 50 MB.','حجم ویدیو باید حداکثر ۵۰ مگابایت باشد.'],
   'فایل ویدیو MP4 معتبر نیست.':['Choose a valid MP4 video.','فایل ویدیو MP4 معتبر نیست.'],
   'شناسه مدیر ربات تنظیم نشده است.':['Configure the bot owner ID first.','شناسه مدیر ربات تنظیم نشده است.'],
   'بارگذاری ویدیو در تلگرام انجام نشد؛ اتصال ربات و گفتگوی مدیر را بررسی کنید.':['Telegram upload failed. Check the bot connection and make sure the owner has started the bot.','بارگذاری ویدیو در تلگرام انجام نشد؛ اتصال ربات و گفتگوی مدیر را بررسی کنید.'],
   'AUTH_REQUIRED':['Please sign in again.','لطفاً دوباره وارد شوید.'],
   'متن صفحه اصلی نمی‌تواند خالی باشد.':['The home message cannot be empty.','متن صفحه اصلی نمی‌تواند خالی باشد.'],
   'متن صفحه اصلی بیش از حد طولانی است؛ حداکثر ۴۰۹۶ نویسه تلگرام.':['The home message is too long. The limit is 4,096 Telegram characters.','متن صفحه اصلی بیش از حد طولانی است؛ حداکثر ۴۰۹۶ نویسه تلگرام.'],
   'وضعیت دکمه معتبر نیست.':['Select a valid button status.','وضعیت دکمه معتبر نیست.']
  };
  if(known[message])return s(...known[message]);
  const translated=translateUiText(message,language);
  if(translated!==message)return translated;
  return s('Could not save or load these settings. Check the fields and try again.','ذخیره یا بارگذاری تنظیمات انجام نشد. فیلدها را بررسی و دوباره تلاش کنید.');
 }
 return {language,s,failure};
}

