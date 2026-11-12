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
