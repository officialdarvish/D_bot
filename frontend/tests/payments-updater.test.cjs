const {test,afterEach}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const Module=require('node:module');
const ts=require('typescript');
const {JSDOM}=require('jsdom');
const frontend=path.resolve(__dirname,'..');
const resolve=Module._resolveFilename;
Module._resolveFilename=function(name,parent,...args){return resolve.call(this,name.startsWith('@/')?path.join(frontend,name.slice(2)):name,parent,...args)};
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true,target:ts.ScriptTarget.ES2020}}).outputText,file);
require.extensions['.css']=(module)=>{module.exports={}};
function environment(){
 const dom=new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>',{url:'https://bot.example.com/admin',pretendToBeVisual:true});
 for(const key of ['window','document','HTMLElement','HTMLInputElement','Element','Document','Text','Node','NodeFilter','MutationObserver','FormData','File','localStorage'])global[key]=dom.window[key];
 Object.defineProperty(global,'navigator',{value:dom.window.navigator,configurable:true,writable:true});
 global.requestAnimationFrame=dom.window.requestAnimationFrame.bind(dom.window);global.cancelAnimationFrame=dom.window.cancelAnimationFrame.bind(dom.window);
 global.IS_REACT_ACT_ENVIRONMENT=true;
 document.cookie='dbot_csrf_token=csrf';
 return dom;
}
let dom=environment();
const React=require('react');const {act}=React;const {createRoot}=require('react-dom/client');
const {UiLanguageProvider}=require('../lib/ui-language.tsx');
const {PaymentMethods}=require('../components/payment-methods.tsx');
const {SystemUpdate}=require('../components/system-update.tsx');
let root;
afterEach(async()=>{if(root)await act(async()=>root.unmount());root=null;dom.window.close();dom=environment()});
function response(value,status=200){return {ok:status<400,status,headers:{get:()=> 'application/json'},json:async()=>value,url:'https://bot.example.com/admin/api',redirected:false}}
async function render(element,language='en'){localStorage.setItem('dbot_ui_language',language);root=createRoot(document.getElementById('root'));await act(async()=>{root.render(React.createElement(UiLanguageProvider,null,element))})}
const text=()=>document.body.textContent;
function button(label){const found=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()===label||b.querySelector('strong')?.textContent===label||b.getAttribute('aria-label')===label);assert.ok(found,`Missing button: ${label}`);return found}
async function click(label){await act(async()=>button(label).click())}
async function input(element,value){await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set.call(element,value);element.dispatchEvent(new window.Event('input',{bubbles:true}))})}

for(const language of ['en','fa'])test(`Payments + configures Bridge with shared saved credentials (${language})`,async()=>{
 let config={enabled:false,url:'',bot_username:'',currency:'IRT'},saved=false;const posts=[];
 global.fetch=async(url,opts={})=>{
  if(String(url).endsWith('/admin/darvish-bridge/save')){
   assert.equal(opts.headers['X-CSRF-Token'],'csrf');const fields=Object.fromEntries(opts.body.entries());posts.push(fields);
   config={enabled:fields.enabled==='1',url:fields.url,bot_username:fields.bot_username,currency:fields.currency};saved=true;
   return response({ok:true});
  }
  assert.ok(String(url).includes('/admin/api/v2/darvish-bridge'));
  return response({ok:true,config,key_saved:saved,secret_saved:saved});
 };
 let bank=0;
 await render(React.createElement(PaymentMethods,{addCard:()=>bank++,accountCount:0,query:'',reloadKey:0,setAuthRequired:()=>{}}),language);
 await click(language==='fa'?'افزودن روش پرداخت':'Add Payment');
 assert.ok(text().includes(language==='fa'?'کارت / حساب بانکی':'Bank card / account'));
 await click('Darvish Bridge');
 assert.ok(document.querySelector('[role="dialog"]'));assert.ok(text().includes('https://bot.example.com/webhooks/darvish-bridge'));
 const form=document.querySelector('.bridge-connection-form');
 await act(async()=>form.querySelector('[type=checkbox]').click());
 const fields=[...form.querySelectorAll('input:not([type=checkbox])')];
 for(const [i,value] of ['https://bridge.example.com','darvish_bridge_bot','merchant-key','secret-123456789012345678901234'].entries())await input(fields[i],value);
 await act(async()=>form.dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(posts.length,1);assert.equal(posts[0].currency,'IRT');assert.equal(form.querySelector('select').options.length,1);assert.equal(posts[0].enabled,'1');assert.equal(posts[0].key,'merchant-key');
 assert.ok(text().includes('https://bridge.example.com'));assert.ok(!document.body.innerHTML.includes('merchant-key'));
 // Editing a saved connection keeps both secrets blank and optional.
 assert.equal(fields[2].value,'');assert.equal(fields[2].required,false);assert.equal(fields[3].required,false);
 await click(language==='fa'?'بستن':'Close');
 await click(language==='fa'?'افزودن روش پرداخت':'Add Payment');
 await click(language==='fa'?'کارت / حساب بانکی':'Bank card / account');
 assert.equal(bank,1);assert.equal(document.querySelector('[role="dialog"]'),null);
});

const sha='a'.repeat(40);
function updateInfo(ready=true){return {ok:true,installed:{version:'1.4.0',build:2},latest:{version:'1.4.0',build:3,notes:{en:'Update',fa:'آپدیت'}},commit:sha,available:true,host_ready:ready,host:{reason:ready?'connected':'worker_missing',bootstrap_command:'sudo dbot update'},job:{state:'idle'}}}
for(const language of ['en','fa'])test(`Confirmation sends VPS request and displays accepted queue state (${language})`,async()=>{
 let posts=0;
 if(language==='fa')window.history.replaceState({},'', '/private/admin');
 global.fetch=async(url,opts={})=>{
  if(String(url).endsWith('/admin/update/start')){if(language==='fa')assert.equal(url,'/private/admin/update/start');posts++;assert.equal(opts.headers['X-CSRF-Token'],'csrf');assert.equal(opts.body.get('commit'),sha);return response({ok:true,job:{id:'job-1',state:'queued'}})}
  return response(updateInfo());
 };
 await render(React.createElement(SystemUpdate),language);
 await click(language==='fa'?'جزئیات و آپدیت':'Details and update');
 const confirm=button(language==='fa'?'تأیید و آپدیت VPS':'Confirm and update VPS');assert.equal(confirm.disabled,false);
 await act(async()=>confirm.click());assert.equal(posts,1);
 assert.ok(text().includes(language==='fa'?'برای VPS ثبت شد':'sent to the VPS'));
 assert.equal(button(language==='fa'?'آپدیت در حال اجرا است':'Update in progress').disabled,true);
 await act(async()=>confirm.click());assert.equal(posts,1);
});

test('Offline VPS worker gives an actionable error instead of a silently disabled confirmation',async()=>{
 let posts=0;
 global.fetch=async(url)=>String(url).endsWith('/admin/update/start')?(posts++,response({detail:'VPS updater is offline'},409)):response(updateInfo(false));
 await render(React.createElement(SystemUpdate));await click('Details and update');
 assert.ok(text().includes('sudo dbot update'));assert.equal(button('Confirm and update VPS').disabled,false);
 await click('Confirm and update VPS');assert.equal(posts,1);assert.ok(document.querySelector('[role="alert"]'));assert.ok(text().includes('VPS updater is offline'));
 assert.ok(!text().includes('sent to the VPS; queued'));assert.ok(document.querySelector('[role="dialog"]'));
});

test('Changed official commit refreshes before retry and sends the new commit',async()=>{
 const sent=[];let changed=false;
 global.fetch=async(url,opts={})=>{
  if(String(url).endsWith('/admin/update/start')){sent.push(opts.body.get('commit'));if(!changed){changed=true;return response({detail:'Update changed; check again'},409)}return response({ok:true,job:{id:'retry',state:'queued'}})}
  return response({...updateInfo(),commit:changed?'b'.repeat(40):sha});
 };
 await render(React.createElement(SystemUpdate));await click('Details and update');await click('Confirm and update VPS');
 assert.ok(text().includes('Update changed; check again'));await click('Confirm and update VPS');
 assert.deepEqual(sent,[sha,'b'.repeat(40)]);
});

test('Failed updates show stage, exit code and accurate recovery even without a journal message',async()=>{
 global.fetch=async()=>response({...updateInfo(),job:{state:'failed',phase:'building',exit_code:137,recovery:'not_needed',log_file:'update-job.log',error:'Memory pressure suspected'}});
 await render(React.createElement(SystemUpdate));await click('Details and update');
 assert.ok(text().includes('Failed stage:'));assert.ok(text().includes('Command exit code: 137'));
 assert.ok(text().includes('previous version was not replaced'));assert.ok(text().includes('update-job.log'));
 assert.ok(!text().includes('Previous source recovery: False'));
});

test('English Version never renders Persian from bilingual server errors or notes',async()=>{
 global.fetch=async()=>response({...updateInfo(),check_error:'Update check unavailable / بررسی آپدیت در دسترس نیست',job:{state:'failed',error:'Host command failed / اجرای فرمان ناموفق بود; phase=building; Previous version retained / نسخه قبلی حفظ شد'}});
 await render(React.createElement(SystemUpdate));
 assert.equal(/[\u0600-\u06ff]/.test(document.querySelector('.version-card').textContent),false);
 await click('Details and update');
 assert.equal(/[\u0600-\u06ff]/.test(document.querySelector('[role="dialog"]').textContent),false);
 assert.ok(text().includes('Host command failed'));
});

// Exercise the actual plan form and its renderer, without importing unrelated pages.
function planComponents(){
 const source=fs.readFileSync(path.join(frontend,'components/admin-dashboard.tsx'),'utf8');
 const ast=ts.createSourceFile('dashboard.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 const names=new Set(['serverOptions','planForm','resellerPlanForm','FormModal']);
 const pieces=ast.statements.filter(n=>ts.isFunctionDeclaration(n)&&names.has(n.name?.text)).map(n=>n.getText(ast)).join('\n');
 const compiled=ts.transpileModule(pieces,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText;
 const {AdminDialog}=require('../components/admin-dialog.tsx'),{X,CheckCircle2}=require('lucide-react');
 const motion={div:({children,initial,animate,...props})=>React.createElement('div',props,children)};
 return new Function('exports','require','useState','useRef','motion','AdminDialog','X','CheckCircle2',compiled+';return {planForm,resellerPlanForm,FormModal};')({},require,React.useState,React.useRef,motion,AdminDialog,X,CheckCircle2);
}
for(const reseller of [false,true])test(`Plan switches between fixed and custom fields, omits hidden values (${reseller?'reseller':'public'})`,async()=>{
 const {planForm,resellerPlanForm,FormModal}=planComponents();
 const servers=[{id:1,name:'Sanaei',server_type:'xui',inbound_ids:[1]}];
 const form=(reseller?resellerPlanForm:planForm)([{value:1,label:'Category'}],servers);
 form.defaults={...form.defaults,title:'Custom',server_id:1,category_id:1,custom_min_gb:1,custom_max_gb:100,custom_min_days:1,custom_max_days:90,custom_price_gb:10000,custom_price_day:1000,volume_gb:50,duration_days:30};
 const posted=[];
 await render(React.createElement(FormModal,{modal:form,onClose:()=>{},onSubmit:async v=>posted.push(v),show:()=>{},onAuthRequired:()=>{}}));
 const field=name=>document.querySelector(`.field-${name}`);
 assert.ok(field('volume_gb'));assert.equal(field('custom_min_gb'),null);
 await act(async()=>{const select=field('custom_enabled').querySelector('select');select.value='yes';select.dispatchEvent(new window.Event('change',{bubbles:true}))});
 assert.equal(field('volume_gb'),null);assert.equal(field('duration_days'),null);assert.equal(field('price_irt'),null);assert.equal(field('price_usd'),null);assert.equal(field('reseller_validity_days'),null);
 for(const name of ['custom_min_gb','custom_max_gb','custom_min_days','custom_max_days','custom_price_gb','custom_price_day','server_id','inbound_mode'])assert.ok(field(name),name);
 assert.equal(field('pricing_currency').querySelectorAll('option').length,1);
 await act(async()=>document.querySelector('form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(posted.length,1);assert.equal(posted[0].custom_enabled,'yes');assert.equal(posted[0].pricing_currency,'IRT');
 for(const name of ['volume_gb','duration_days','price_irt','price_usd','reseller_validity_days'])assert.equal(posted[0][name],undefined,name);
 await act(async()=>{const select=field('custom_enabled').querySelector('select');select.value='no';select.dispatchEvent(new window.Event('change',{bubbles:true}))});
 assert.ok(field('volume_gb'));assert.equal(field('custom_min_gb'),null);assert.ok(field(reseller?'reseller_validity_days':'duration_days'));
});
test('Editing custom plan preserves enabled mode and saved ranges',async()=>{
 const {planForm,FormModal}=planComponents();const modal=planForm([],[{id:1,name:'NX',server_type:'nx',inbound_ids:[1]}],{id:2,title:'Custom',server_id:1,custom_tariff:{enabled:true,min_gb:4,max_gb:50,min_days:7,max_days:90,price_gb:100,price_day:10}});
 await render(React.createElement(FormModal,{modal,onClose:()=>{},onSubmit:async()=>{},show:()=>{},onAuthRequired:()=>{}}));
 assert.equal(document.querySelector('.field-custom_enabled select').value,'yes');assert.equal(document.querySelector('.field-custom_min_gb input').value,'4');assert.equal(document.querySelector('.field-volume_gb'),null);assert.ok(document.querySelector('.field-hwid_limit'));
});

for(const language of ['en','fa'])test(`Custom home editor inserts variables, previews safely and saves (${language})`,async()=>{
 const {BotHomeSettings}=require('../components/bot-home-settings.tsx');let saved=null;
 global.fetch=async(url,opts)=>{assert.ok(String(url).endsWith('/admin/settings/home-message'));saved=opts.body.get('welcome_text');return response({ok:true})};
 await render(React.createElement(BotHomeSettings,{map:{welcome_text:'Hello ',bot_name:'D BOT',support_username:'@help'},section:'home',show:()=>{},setAuthRequired:()=>{}}),language);
 const editor=document.querySelector('.home-message-editor textarea');assert.ok(editor.id);assert.ok(document.querySelector(`label[for="${editor.id}"]`));assert.equal(editor.maxLength,4096);
 const save=button(language==='fa'?'ذخیره پیام صفحه اصلی':'Save home message');assert.equal(save.disabled,true);
 editor.setSelectionRange(6,6);await click('{bot_name}'+(language==='fa'?'نام ربات':'Bot name'));
 assert.equal(editor.value,'Hello {bot_name}');assert.ok(document.querySelector('.home-message-bubble').textContent.includes('Hello D BOT'));
 assert.equal(save.disabled,false);
 await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(editor,'<b>Hi</b> {support_username}');editor.dispatchEvent(new window.Event('input',{bubbles:true}))});
 assert.equal(document.querySelector('.home-message-bubble b'),null);assert.ok(document.querySelector('.home-message-bubble').textContent.includes('@help'));
 await act(async()=>document.querySelector('.home-message-card form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(saved,'<b>Hi</b> {support_username}');assert.equal(save.disabled,true);assert.ok(document.querySelector('.home-message-heading [role=status]').textContent.includes(language==='fa'?'ذخیره‌شده':'Saved'));
 assert.equal(document.body.textContent.includes('Reseller panel sales button'),false);
});
test('Custom home editor retains unsaved draft when saving fails',async()=>{
 const {BotHomeSettings}=require('../components/bot-home-settings.tsx');let notice='';
 global.fetch=async()=>response({ok:false,message:'Cannot save'},500);
 await render(React.createElement(BotHomeSettings,{map:{welcome_text:'Hello'},section:'home',show:m=>notice=m,setAuthRequired:()=>{}}));
 const editor=document.querySelector('textarea');
 await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(editor,'New home');editor.dispatchEvent(new window.Event('input',{bubbles:true}))});
 await act(async()=>document.querySelector('form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(editor.value,'New home');assert.ok(notice);assert.equal(button('Save home message').disabled,false);assert.equal(document.querySelector('.home-message-heading [role=status]').textContent,'Unsaved changes');
});

test('Bridge dialog stays open while saving and unlocks after validation',async()=>{
 let finish;const pending=new Promise(resolve=>finish=resolve);
 const info={ok:true,config:{enabled:true,url:'https://bridge.example.com',bot_username:'bridge_bot',currency:'IRT'},key_saved:true,secret_saved:true};
 global.fetch=async(url)=>String(url).endsWith('/admin/darvish-bridge/save')?pending:response(info);
 await render(React.createElement(PaymentMethods,{addCard:()=>{},accountCount:0,query:'',reloadKey:0,setAuthRequired:()=>{}}));
 await click('Add Payment');await click('Darvish Bridge');
 const dialog=document.querySelector('[role=dialog]');assert.ok(dialog.querySelector('.bridge-layout'));assert.equal(dialog.querySelectorAll('fieldset').length,2);
 const form=dialog.querySelector('form');
 await act(async()=>form.dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(button('Close').disabled,true);
 await act(async()=>document.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 assert.ok(document.querySelector('[role=dialog]'));
 await act(async()=>{finish(response({ok:true}));await pending});
 assert.equal(button('Close').disabled,false);await click('Close');assert.equal(document.querySelector('[role=dialog]'),null);
});

test('Bridge load failure offers retry and keeps connection fields disabled',async()=>{
 const {BridgeSettings}=require('../components/bridge-settings.tsx');let fail=true;
 global.fetch=async()=>fail?response({ok:false,message:'Bridge connection failed'},503):response({ok:true,config:{enabled:false,url:'https://bridge.example.com',bot_username:'bridge_bot',currency:'IRT'},key_saved:true,secret_saved:true});
 await render(React.createElement(BridgeSettings));
 assert.ok(document.querySelector('[role=alert]'));assert.equal(document.querySelector('input[type=url]').disabled,true);
 assert.ok(text().includes('Connection settings unavailable.'));fail=false;await click('Retry');
 assert.equal(document.querySelector('[role=alert]'),null);assert.equal(document.querySelector('input[type=url]').disabled,false);assert.equal(document.querySelector('input[type=password]').value,'');assert.ok(document.querySelector('label[for]'));
});

function miniResponse(data,status=200,type='application/json'){
 return {status,ok:status>=200&&status<300,redirected:false,type:'basic',headers:{get:()=>type},text:async()=>type==='application/json'?JSON.stringify(data):data};
}
test('Mini App transport rejects HTML, truncated JSON and redirects with actionable errors',async()=>{
 const {miniAppRequest}=require('../lib/miniapp-http.ts');
 for(const [value,status,type] of [['<html>too large</html>',413,'text/html'],['<html>gateway timeout</html>',504,'text/html'],['<html>login</html>',200,'text/html']]){
  global.fetch=async()=>miniResponse(value,status,type);
  await assert.rejects(()=>miniAppRequest('/funding/1/receipt','signed',new FormData()),e=>e.message.length>10&&!/expected pattern|<html>/.test(e.message));
 }
 global.fetch=async()=>({...miniResponse({},200),text:async()=>'{"id":'});
 await assert.rejects(()=>miniAppRequest('/funding/1','signed'),/پاسخ سرور معتبر نیست/);
 global.fetch=async()=>({...miniResponse({},0),type:'opaqueredirect'});
 await assert.rejects(()=>miniAppRequest('/funding/1','signed'),/هدایت/);
 global.fetch=async()=>miniResponse({detail:'حساب نمایندگی فعال نیست'},403);
 await assert.rejects(()=>miniAppRequest('/funding/quote','signed',{}),/حساب نمایندگی فعال نیست/);
});

for(const mode of ['retry','committed'])test(`Reseller volume purchase and receipt upload recover from proxy errors (${mode})`,async()=>{
 const {MiniAppFunding}=require('../components/miniapp-native.tsx');const {miniAppRequest}=require('../lib/miniapp-http.ts');
 const api=(path,body)=>miniAppRequest(path,'signed-telegram',body);let uploads=0,creates=0,reads=0;
 const order={id:73,key:'key',kind:'reseller_package',status:'waiting_receipt',title:'Reseller volume',amount:90000,receipt_uploaded:false,card:{number:'6037000000000001',owner:'Admin'}};
 global.fetch=async(url,opts={})=>{
  assert.equal(opts.headers['X-Telegram-Init-Data'],'signed-telegram');assert.equal(opts.redirect,'manual');
  if(url.endsWith('/reseller/catalog'))return miniResponse({servers:[{id:2,name:'Reseller server'}],packages:[{id:12,server_id:2,title:'100 GB',volume_gb:100,price:'90,000'}],default_server_id:2});
  if(url.endsWith('/funding/quote')){const p=JSON.parse(opts.body);assert.equal(p.server_id,2);assert.equal(p.package_id,12);return miniResponse({amount:90000,title:'100 GB',balance:250000,methods:['card']})}
  if(url.endsWith('/funding')){creates++;return miniResponse(order)}
  if(url.endsWith('/receipt')){uploads++;assert.ok(opts.body instanceof FormData);assert.equal(opts.headers['Content-Type'],undefined);assert.equal(opts.body.get('file').name,'رسید.png');if(uploads===1)return miniResponse('<html>proxy error</html>',mode==='retry'?413:504,'text/html');return miniResponse({...order,status:'waiting_approval',receipt_uploaded:true})}
  if(url.endsWith('/funding/73')){reads++;return miniResponse(mode==='committed'?{...order,status:'waiting_approval',receipt_uploaded:true}:order)}
  throw Error('Unexpected route '+url);
 };
 await render(React.createElement(MiniAppFunding,{kind:'reseller_package',payg:false,api,onBack:()=>{},onDone:()=>{}}));
 await click('بررسی و ادامه پرداخت');await click('کارت به کارت و ارسال رسید');
 const picker=document.querySelector('input[type=file]');
 await act(async()=>{Object.defineProperty(picker,'files',{configurable:true,value:[new File(['png-data'],'رسید.png',{type:'image/png'})]});picker.dispatchEvent(new window.Event('change',{bubbles:true}))});
 await click('ارسال رسید برای بررسی');
 if(mode==='retry'){assert.ok(document.querySelector('[role=alert]'));assert.equal(button('ارسال رسید برای بررسی').disabled,false);await click('ارسال رسید برای بررسی')}
 assert.ok(text().includes('منتظر تأیید مدیر'));assert.equal(document.querySelector('[role=alert]'),null);assert.equal(creates,1);assert.equal(uploads,mode==='retry'?2:1);assert.equal(reads,1);assert.ok(!text().includes('expected pattern'));
});

test('Receipt size/type validation runs before any upload or status requests',async()=>{
 const {uploadMiniAppReceipt}=require('../lib/miniapp-http.ts');let calls=0;const api=async()=>{calls++;return {}};
 for(const file of [new File([],'empty.png',{type:'image/png'}),new File(['bad'],'receipt.heic',{type:'image/heic'})])await assert.rejects(()=>uploadMiniAppReceipt(api,'/receipt','/status',file));
 const big=new File(['data'],'large.jpg',{type:'image/jpeg'});Object.defineProperty(big,'size',{value:8*1024**2+1});await assert.rejects(()=>uploadMiniAppReceipt(api,'/receipt','/status',big),/۸ مگابایت/);assert.equal(calls,0);
});

test('Tutorials use distinct cards, native disclosure controls and refreshable video URLs',async()=>{
 const {MiniAppContent}=require('../components/miniapp-content.tsx');let calls=0,paused=0;
 window.HTMLMediaElement.prototype.pause=function(){paused++};
 const api=async(path)=>{assert.equal(path,'/content');calls++;return {rules:'Rules',tutorials:[{id:'happ-android',name:'Happ',platform:'android',text:'First instruction',download_url:'https://example.com/happ',video_url:`/api/miniapp/tutorial-video/happ-android?expires=2000000000&token=${calls}`},{id:'happ-ios',name:'Happ',platform:'ios',text:'iOS instruction',download_url:''}]}};
 await render(React.createElement(MiniAppContent,{kind:'tutorials',api,onBack:()=>{}}));
 const cards=document.querySelectorAll('details.ma-tutorial');assert.equal(cards.length,2);
 const summary=cards[0].querySelector('summary'),video=cards[0].querySelector('video');
 assert.ok(summary.querySelector('.ma-tutorial-icon'));assert.ok(summary.querySelector('.ma-tutorial-chevron'));assert.ok(summary.textContent.includes('برای مشاهده آموزش بزنید'));
 assert.equal(video.preload,'none');assert.equal(video.controls,true);assert.ok(video.hasAttribute('playsinline'));
 await act(async()=>{summary.click();await new Promise(resolve=>setTimeout(resolve,10))});
 assert.equal(cards[0].open,true);assert.equal(video.preload,'metadata');assert.ok(summary.textContent.includes('بستن آموزش'));
 assert.ok(cards[0].querySelector('a').rel.includes('noopener'));video.currentTime=95;
 await act(async()=>video.dispatchEvent(new window.Event('error')));assert.ok(document.querySelector('[role=alert]'));
 await click('بارگذاری دوباره ویدیو');assert.equal(calls,2);assert.ok(video.getAttribute('src').endsWith('token=2'));assert.equal(document.querySelector('[role=alert]'),null);
 Object.defineProperty(video,'duration',{configurable:true,value:200});video.currentTime=0;
 await act(async()=>video.dispatchEvent(new window.Event('loadedmetadata')));assert.equal(video.currentTime,95);
 await act(async()=>{summary.click();await new Promise(resolve=>setTimeout(resolve,10))});assert.equal(cards[0].open,false);assert.equal(paused,1);
});

for(const language of ['en','fa'])test(`Custom journeys persist related button text and named templates (${language})`,async()=>{
 const {CustomSection}=require('../components/custom-section.tsx');
 const rows=[{key:'home',default:'Welcome',current:'Welcome',kind:'message',legacy_key:'welcome_text',category:'شروع و صفحه اصلی',section:'ورود، قوانین و منوی اصلی',source:'app/database/defaults.py',line:1,customized:false},
 {key:'buy-button',default:'Buy',current:'Buy',kind:'button',legacy_key:'button_buy_text',category:'منو و دکمه‌های اصلی',section:'دکمه‌های قابل مشاهده کاربر',source:'app/bot/keyboards/common.py',line:1,customized:false,enabled:true},
 {key:'buy-message',default:'Choose a plan',current:'Choose a plan',kind:'message',category:'خرید و پرداخت',section:'فرآیند خرید',source:'app/bot/handlers/public/buy.py',line:1,customized:false},
 {key:'wallet-message',default:'Wallet balance',current:'Wallet balance',kind:'message',category:'حساب کاربری و کیف پول',section:'حساب کاربری',source:'app/bot/handlers/public/account.py',line:1,customized:false}];
 let posted=null,profileName='';global.fetch=async(url,options={})=>{
  if(options.method==='POST'){
   const fields=Object.fromEntries(options.body.entries());
   if(String(url).endsWith('/custom-profiles'))profileName=fields.name;
   else{posted=fields;const row=rows.find(r=>r.key===fields.key);row.current=fields.value;row.customized=true}
   return response({ok:true,id:'abc'});
  }
  if(String(url).endsWith('/custom-profiles'))return response({ok:true,items:profileName?[{id:'abc',name:profileName}]:[]});
  return response({ok:true,items:rows,total:rows.length,modified:0});
 };
 await render(React.createElement(CustomSection,{reloadKey:0,show:()=>{},setAuthRequired:()=>{}}),language);
 assert.ok(document.querySelector('.cj-message-name').textContent.includes(language==='fa'?'پیام صفحه اصلی ربات':'Bot home message'));
 const menu=document.querySelector('.cj-menu .cj-keyboard button');await act(async()=>menu.click());
 assert.ok(document.querySelector('.cj-flow').textContent.includes('Choose a plan'));assert.ok(!document.querySelector('.cj-flow').textContent.includes('Wallet balance'));
 await act(async()=>document.querySelector('.cj-flow-buttons .cj-keyboard button').click());
 const editor=document.querySelector('.cj-editor textarea');
 await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(editor,'Shop plans');editor.dispatchEvent(new window.Event('input',{bubbles:true}))});
 await click(language==='fa'?'ذخیره و اعمال':'Save and apply');assert.equal(posted.key,'buy-button');assert.equal(posted.value,'Shop plans');assert.equal(document.querySelector('[role=dialog]'),null);assert.ok(document.querySelector('.cj-menu').textContent.includes('Shop plans'));
 await click(language==='fa'?'ذخیره به‌عنوان قالب':'Save as template');await input(document.querySelector('.cj-new-template input'),'Shop style');
 await act(async()=>document.querySelector('.cj-new-template').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true})));
 assert.equal(profileName,'Shop style');assert.ok(document.querySelector('.cj-template-actions select').textContent.includes('Shop style'));
});

test('Bot preview supports formatting without executing markup or opening links',async()=>{
 const {BotTemplatePreview}=require('../components/bot-template-preview.tsx');
 await render(React.createElement(BotTemplatePreview,{text:'<b>Bold</b> <i>Italic</i> <a href="javascript:alert(1)">Link</a> <img src="https://evil.test/x" onerror="alert(1)"><script>alert(1)</script> &lt;safe&gt;'}));
 assert.equal(document.querySelector('b').textContent,'Bold');assert.equal(document.querySelector('i').textContent,'Italic');assert.equal(document.querySelectorAll('a,img,script').length,0);assert.ok(text().includes('<safe>'));
});

test('Every editable catalog item belongs to an accessible bot journey',()=>{
 const {customJourney,journeys}=require('../lib/custom-journeys.ts');
 for(const source of ['app/bot/handlers/public/buy.py','app/bot/handlers/public/test_account.py','unknown.py','app/jobs/service_alerts.py'])assert.ok(journeys.some(j=>j.id===customJourney({source,legacy_key:null})));
});

test('First setup stage offers a small restore entry without leaking keys into wizard saves',async()=>{
 const {spawnSync}=require('node:child_process');
 const source='<html><head></head><body><header class="setup-topbar"></header><main><form><div class="steps"><section class="step"></section></div><div class="actions"><button class="btn" type="submit">Save</button></div></form></main></body></html>';
 const python=path.join(path.dirname(frontend),'.venv/bin/python');
 const result=spawnSync(fs.existsSync(python)?python:'python3',['-c','from app.services.setup_steps import staged; print(staged('+JSON.stringify(source)+',{},"/private","csrf-demo",[]))'],{cwd:path.dirname(frontend),encoding:'utf8',env:{...process.env,BOT_TOKEN:'123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',DATABASE_URL:'sqlite+aiosqlite:///:memory:'}});assert.equal(result.status,0,result.stderr);
 let request=null;const wizard=new JSDOM(result.stdout,{url:'https://bot.example.com/private/setup',runScripts:'dangerously',beforeParse(window){window.confirm=()=>true;window.fetch=async(url,options)=>{request={url,options};return {ok:false,status:409,type:'basic',json:async()=>({ok:false,code:'backup_password_required'})}}}});
 try{
  const d=wizard.window.document;assert.equal(d.querySelectorAll('form').length,1);assert.ok(d.querySelector('.step.current .setup-restore'));
  assert.equal(d.querySelectorAll('#setupServers li').length,0);
  const file=d.querySelector('[data-setup-restore=file]'),password=d.querySelector('[data-setup-restore=aes_password]');
  assert.equal(file.hasAttribute('name'),false);assert.equal(password.hasAttribute('name'),false);
  Object.defineProperty(file,'files',{value:[new wizard.window.File(['encrypted'],'backup.dbot')],configurable:true});password.value='private-password';
  d.getElementById('setupRestoreRun').click();await new Promise(resolve=>setTimeout(resolve,15));
  assert.equal(request.url,'/private/admin/backup/restore');assert.equal(request.options.headers['X-CSRF-Token'],'csrf-demo');assert.equal(request.options.body.get('setup_restore'),'1');assert.equal(request.options.body.get('aes_password'),'private-password');
  assert.ok(d.getElementById('setupRestoreStatus').textContent.includes('رمز اصلی'));assert.equal(file.disabled,false);assert.equal(password.value,'private-password');
 }finally{wizard.window.close()}
});

for(const language of ['en','fa'])test(`Test-account template editor saves an independent template and keeps failed-save drafts (${language})`,async()=>{
 const {DeliveryTemplates}=require('../components/delivery-templates.tsx');
 const config={ok:true,active:'legacy',templates:[],presets:[{id:'simple',name:'Simple',text:'Trial {username}'},{id:'legacy',name:'Default',text:'Old {username}'}],fields:['username','traffic','duration','subscription_line']};
 let saved=null,attempts=0,dirty=false;
 global.fetch=async(url,options={})=>{
  assert.ok(String(url).includes('scope=trial'));
  if(!options.method)return response(config);
  const fields=Object.fromEntries(options.body.entries());
  if(String(url).includes('/preview?'))return response({ok:true,preview:'Trial test_000001 — 0.5 GB — 1 day'});
  attempts++;if(attempts===1)return response({detail:'offline'},503);
  saved=fields;return response({ok:true,active:fields.active,templates:JSON.parse(fields.templates_json)});
 };
 await render(React.createElement(DeliveryTemplates,{scope:'trial',reloadKey:0,show:()=>{},setAuthRequired:()=>{},onDirtyChange:v=>dirty=v}),language);
 assert.ok(text().includes(language==='fa'?'قالب‌های ارسال اکانت تست':'Test account delivery templates'));
 await click(language==='fa'?'افزودن قالب متنی':'Add text template');
 await input(document.querySelector('input'),language==='fa'?'تست ویژه':'Trial style');
 const editor=document.querySelector('textarea');
 await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(editor,'Trial ');editor.dispatchEvent(new window.Event('input',{bubbles:true}))});
 await click('{username}');assert.equal(editor.value,'Trial {username}');assert.equal(dirty,true);
 await click(language==='fa'?'پیش‌نمایش نمونه':'Preview sample');assert.ok(text().includes('test_000001'));
 await click(language==='fa'?'انتخاب برای ارسال':'Use for delivery');
 await click(language==='fa'?'ذخیره قالب‌ها و انتخاب پیش‌فرض':'Save templates and default');assert.equal(editor.value,'Trial {username}');assert.equal(saved,null);assert.equal(dirty,true);
 await click(language==='fa'?'ذخیره قالب‌ها و انتخاب پیش‌فرض':'Save templates and default');
 const row=JSON.parse(saved.templates_json)[0];assert.equal(row.text,'Trial {username}');assert.equal(saved.active,row.id);assert.equal(dirty,false);
});

for(const language of ['en','fa'])test(`Custom protects unsaved test templates when switching sections (${language})`,async()=>{
 const {CustomSection}=require('../components/custom-section.tsx');
 const rows=[{key:'home',default:'Welcome',current:'Welcome',kind:'message',legacy_key:'welcome_text',section:'Entry',source:'app/database/defaults.py',customized:false},...['test_account','buy'].map(name=>({key:name,default:name,current:name,kind:'button',legacy_key:`button_${name}_text`,section:'Buttons',source:'app/bot/keyboards/common.py',customized:false,enabled:true}))];
 const config={ok:true,active:'legacy',templates:[],presets:[{id:'simple',name:'Simple',text:'Trial {username}'},{id:'legacy',name:'Default',text:'Old {username}'}],fields:['username']};
 global.fetch=async(url)=>String(url).includes('delivery-templates')?response(config):String(url).endsWith('custom-profiles')?response({ok:true,items:[]}):response({ok:true,items:rows,total:rows.length,modified:0});
 let prompts=0,discard=false;window.confirm=()=>{prompts++;return discard};
 await render(React.createElement(CustomSection,{reloadKey:0,show:()=>{},setAuthRequired:()=>{}}),language);
 const menu=label=>[...document.querySelectorAll('.cj-menu button')].find(b=>b.textContent===label);
 await act(async()=>menu('test_account').click());
 await click(language==='fa'?'افزودن قالب متنی':'Add text template');
 await act(async()=>document.querySelector('.cj-flow-buttons button').click());assert.equal(document.querySelector('[role=dialog]'),null);
 await act(async()=>menu('buy').click());assert.equal(prompts,1);assert.ok(document.querySelector('.delivery-templates'));assert.ok(document.querySelector('.cj-flow h2').textContent.includes(language==='fa'?'اکانت تست':'Test account'));
 discard=true;await act(async()=>menu('buy').click());assert.equal(prompts,2);assert.equal(document.querySelector('.delivery-templates'),null);assert.ok(document.querySelector('.cj-flow h2').textContent.includes(language==='fa'?'خرید':'Purchase'));
});

test('Custom Mini App edits persist, preview literally and reset to the default', async () => {
 const {CustomSection}=require('../components/custom-section.tsx');
 const {miniAppText}=require('../lib/miniapp-copy.ts');
 const greeting='home.text.greeting';
 const overrides={};
 let posts=0;
 global.fetch=async(url,options={})=>{
  if(String(url).endsWith('/miniapp/texts')){
   if(options.method==='POST'){
    assert.equal(options.headers['X-CSRF-Token'],'csrf');
    const changes=JSON.parse(options.body.get('texts_json'));
    assert.deepEqual(Object.keys(changes),[greeting]);
    if(changes[greeting])overrides[greeting]=changes[greeting];
    else delete overrides[greeting];
    posts++;
    return response({ok:true,changes});
   }
   return response({ok:true,overrides:{...overrides}});
  }
  if(String(url).endsWith('/admin/api/v2/miniapp'))return response({ok:true,config:{enabled:true,title:'Old Brand',accent:'#ff0000',welcome:'سلام',support_username:'',links:[]}});
  return response({ok:true,items:[],total:0,modified:0});
 };
 await render(React.createElement(CustomSection,{reloadKey:0,show:()=>{},setAuthRequired:()=>{}}));
 await click('Mini App');
 await input(document.querySelector('input[type="search"]'),'{name}');
 await act(async()=>document.querySelector('.cj-miniapp-results button').click());
 const editor=document.querySelector('.cj-editor textarea');
 async function change(value){await act(async()=>{Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set.call(editor,value);editor.dispatchEvent(new window.Event('input',{bubbles:true}))})}
 await change('درود');
 assert.equal(button('Save text').disabled,true);
 await change('درود <b>{name}</b>');
 assert.equal(document.querySelector('.cj-live-preview b'),null);
 await click('Save text');
 assert.equal(posts,1);
 assert.equal(miniAppText(overrides,greeting,{name:'کاربر'}),'درود <b>کاربر</b>');
 await act(async()=>document.querySelector('.cj-miniapp-results button').click());
 await click('Restore default');
 assert.equal(posts,2);
 assert.equal(miniAppText(overrides,greeting,{name:'کاربر'}),'سلام، کاربر');
 await click('Settings and links');
 assert.equal(document.querySelector('input[type="color"]'),null);
 assert.ok(text().includes('D BOT'));
 assert.ok(!document.body.innerHTML.includes('Old Brand'));
});
