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
 let config={enabled:false,url:'',bot_username:'',currency:'USDT'},saved=false;const posts=[];
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
 assert.equal(posts.length,1);assert.equal(posts[0].enabled,'1');assert.equal(posts[0].key,'merchant-key');
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
