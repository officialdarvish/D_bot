export type CustomItem={key:string;default:string;current:string;category:string;section:string;kind:string;source:string;line:number;symbol?:string;placeholders?:string[];customized:boolean;enabled?:boolean|null;legacy_key?:string|null};
export const journeys=[
 {id:'home',en:'Home & shared buttons',fa:'خانه و دکمه‌های مشترک'},
 {id:'buy',en:'Purchase & payment',fa:'خرید و پرداخت'},
 {id:'services',en:'Configs, renewal & delivery',fa:'کانفیگ، تمدید و تحویل'},
 {id:'wallet',en:'Account & wallet',fa:'حساب کاربری و کیف پول'},
 {id:'trial',en:'Test account',fa:'اکانت تست'},
 {id:'reseller',en:'Reseller',fa:'نمایندگی'},
 {id:'support',en:'Support & tickets',fa:'پشتیبانی و تیکت'},
 {id:'referral',en:'Referral',fa:'دعوت و پورسانت'},
 {id:'rules',en:'Rules',fa:'قوانین'},
 {id:'tutorials',en:'Tutorials',fa:'آموزش‌ها'},
 {id:'alerts',en:'Service alerts',fa:'هشدارهای سرویس'},
 {id:'other',en:'Other messages',fa:'سایر پیام‌ها'},
];
export function customJourney(item:CustomItem):string{
 const key=item.legacy_key||'';
 if(key==='welcome_text')return 'home';if(key==='rules_text')return 'rules';
 const names:Record<string,string>={buy:'buy',my_services:'services',convert:'services',query:'services',account:'wallet',wallet_topup:'wallet',test_account:'trial',tickets:'support',referral:'referral',reseller_request:'reseller',reseller_menu:'reseller',panel_sales:'reseller',tutorials:'tutorials',rules:'rules',admin:'home'};
 const main=key.match(/^button_(.+)_text$/);if(main)return names[main[1]]||'home';
 const source=item.source;
 if(/reseller|panel_reseller/.test(source))return 'reseller';
 if(/test_account/.test(source))return 'trial';
 if(/tickets|private_messages/.test(source))return 'support';
 if(/\/buy\.py/.test(source))return 'buy';
 if(/my_services|service_presenter|profile_delivery|renewal_delivery/.test(source))return 'services';
 if(/\/account\.py/.test(source))return 'wallet';
 if(/referral/.test(source))return 'referral';
 if(/service_alerts|service_cleanup/.test(source))return 'alerts';
 if(/handlers\/start|keyboards\/common/.test(source))return 'home';
 return 'other';
}
