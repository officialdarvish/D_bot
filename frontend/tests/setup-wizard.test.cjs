const {test}=require('node:test');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom');
const project=path.resolve(__dirname,'../..');
// Render the actual setup template without importing database/API startup code.
const html=execFileSync('python3',['-c',`
import ast,html,sys,types
from pathlib import Path
from types import SimpleNamespace
package=types.ModuleType('app.services')
package.__path__=[str(Path('app/services').resolve())]
sys.modules['app.services']=package
from app.services.setup_steps import staged
from app.services.setup_theme import SETUP_WIZARD_CSS
source=ast.parse(Path('app/api/admin_web.py').read_text())
fn=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_setup_wizard_html')
ns={'Request':object,'e':lambda x:html.escape(str(x),quote=True),'SETUP_WIZARD_CSS':SETUP_WIZARD_CSS,'panel_stylesheets':lambda:'','_with_web_prefix':lambda r,p:'/private'+p,'_session_csrf_token':lambda r:'test-csrf','RULES_TEXT_DEFAULT':'Rules','WELCOME_TEXT_DEFAULT':'Welcome'}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'setup-template','exec'),ns)
v={'bot_name':'D BOT','support_username':'@support','web_path':'private'}
print(staged(ns['_setup_wizard_html'](None,v),v,'/private','test-csrf',[SimpleNamespace(id=1,name='Existing',server_type='nx')]))
`],{cwd:project,encoding:'utf8'});
function environment(reply){
 const calls=[],errors=[];const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(html,{url:'https://bot.example/private/setup',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){
  w.localStorage.setItem('dbot_ui_language','en');w.confirm=()=>false;
  w.fetch=async(url,options)=>{calls.push({url,options});return reply(url,options)};
 }});
 return {dom,document:dom.window.document,calls,errors};
}
const response=(json,status=200,type='application/json')=>({ok:status>=200&&status<300,status,type:'basic',headers:{get:()=>type},json:async()=>json});
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
test('setup add requests JSON once and appends the saved server',async()=>{
 const x=environment(()=>response({ok:true,message:'NX saved'}));try{
  x.document.querySelector('[data-server=name]').value='NX new';
  x.document.getElementById('setupAddServer').click();await tick();
  assert.equal(x.calls.length,1);assert.equal(x.calls[0].url,'/private/admin/servers/add');
  assert.equal(x.calls[0].options.headers.Accept,'application/json');
  assert.equal(x.calls[0].options.headers['X-Requested-With'],'fetch');
  assert.equal(x.calls[0].options.headers['X-CSRF-Token'],'test-csrf');
  assert.equal(x.calls[0].options.redirect,'manual');
  assert.equal(x.document.querySelectorAll('#setupServers li').length,2);
  assert.equal(x.document.getElementById('setupServers').hidden,true);
  assert.deepEqual([...x.document.querySelectorAll('#setupServers li')].map(el=>el.textContent),['Existing','NX new']);
  const success=x.document.getElementById('setupServerSuccess');
  assert.equal(success.hidden,false);
  assert.equal(success.textContent,'Your server has been added successfully.');
  x.document.getElementById('setupLanguage').click();
  assert.equal(success.textContent,'سرور شما با موفقیت اضافه شد.');
  x.document.getElementById('setupLanguage').click();
  assert.equal(success.textContent,'Your server has been added successfully.');
  assert.equal(x.document.getElementById('setupError').textContent,'');assert.deepEqual(x.errors,[]);
 }finally{x.dom.window.close()}
});
test('HTML response shows a clear error and never retries an ambiguous add',async()=>{
 const x=environment(()=>({...response(null,200,'text/html'),json:async()=>{throw new SyntaxError('Unexpected token <')}}));try{
  x.document.getElementById('setupAddServer').click();await tick();
  assert.match(x.document.getElementById('setupError').textContent,/non-JSON page/);
  assert.equal(x.document.getElementById('setupServerSuccess').hidden,true);
  assert.equal(x.document.querySelectorAll('#setupServers li').length,1);
  assert.equal(x.calls.length,1);assert.deepEqual(x.errors,[]);
  assert.equal(x.document.getElementById('setupAddServer').disabled,false);
 }finally{x.dom.window.close()}
});
test('expired session/manual redirect is handled before parsing any JSON',async()=>{
 for(const status of [401,303]){
  const x=environment(()=>({...response(null,status),json:async()=>{throw Error('Must not parse')}}));try{
   x.document.getElementById('setupAddServer').click();await tick();
   assert.match(x.document.getElementById('setupError').textContent,/session expired/);
   assert.equal(x.calls.length,1);assert.deepEqual(x.errors,[]);
  }finally{x.dom.window.close()}
 }
});
test('progress save handles HTML without advancing the stage',async()=>{
 const x=environment(()=>response(null,502,'text/html'));try{
  x.document.getElementById('setupNext').click();await tick();
  assert.match(x.document.getElementById('setupError').textContent,/non-JSON page/);
  assert.equal(x.document.getElementById('setupServerSuccess').hidden,true);
  assert.match(x.document.querySelector('.step.current h2').textContent,/Servers/);
  assert.equal(x.calls[0].url,'/private/setup/progress');assert.equal(x.calls.length,1);
 }finally{x.dom.window.close()}
});

test('a failed second save clears the previous success message',async()=>{
 let attempt=0;
 const x=environment(()=>++attempt===1?response({ok:true}):response({ok:false,message:'Connection failed'},400));try{
  const button=x.document.getElementById('setupAddServer');
  button.click();await tick();
  assert.equal(x.document.getElementById('setupServerSuccess').hidden,false);
  button.click();await tick();
  const success=x.document.getElementById('setupServerSuccess');
  assert.equal(success.hidden,true);assert.equal(success.textContent,'');
  x.document.getElementById('setupLanguage').click();
  assert.equal(success.textContent,'');
  assert.equal(x.document.getElementById('setupError').textContent,'Connection failed');
  assert.equal(x.document.querySelectorAll('#setupServers li').length,2);
 }finally{x.dom.window.close()}
});

test('step navigation stays synchronized through every stage in both languages',async()=>{
 const x=environment(()=>response({ok:true}));try{
  const {document:d,dom}=x;
  assert.equal(d.querySelector('.setup-workspace > form')?.tagName,'FORM');
  assert.ok(d.querySelector('.setup-stepbar #setupStepList'));
  assert.equal(d.querySelector('iframe[data-src$="/setup/options/settings"]'),null);
  d.querySelectorAll('[name^=feature_]').forEach(field=>field.checked=true);
  let count=0;
  while(!d.getElementById('setupNext').hidden){
   const current=d.querySelector('.step.current');
   assert.equal(d.querySelectorAll('.step.current').length,1);
   assert.equal(d.querySelectorAll('[aria-current=step]').length,1);
   assert.equal(d.querySelector('[aria-current=step] span:last-child').textContent,current.querySelector('h2').textContent);
   const frame=current.querySelector('iframe');
   if(frame){
    assert.equal(d.getElementById('setupNext').textContent,'Continue');
    assert.match(current.querySelector('.setup-step-hint').textContent,/Optional: continue without changes/);
    assert.ok(frame.src.startsWith('https://bot.example/private/setup/options/'));
    frame.dispatchEvent(new dom.window.Event('load'));
    assert.equal(frame.parentElement.getAttribute('aria-busy'),'false');
   }
   d.querySelector('[name=bot_name]').value='D BOT';
   d.querySelector('[name=support_username]').value='@support';
   d.querySelector('[name=welcome_text]').value='Welcome';
   d.querySelector('[name=web_path]').value='private';
   d.getElementById('setupNext').click();await tick();
   assert.equal(d.getElementById('setupError').textContent,'');
   if(++count>25)throw Error('Stage navigation did not finish');
  }
  assert.equal(count,d.querySelectorAll('.step').length-1);
  assert.equal(d.getElementById('setupFinish').hidden,false);
  d.getElementById('setupLanguage').click();
  assert.equal(d.documentElement.dir,'rtl');
  assert.equal(d.getElementById('setupNav').getAttribute('aria-label'),'مراحل راه‌اندازی');
  assert.equal(d.querySelector('[aria-current=step] span:last-child').textContent,d.querySelector('.step.current h2').textContent);
  assert.equal(d.querySelector('iframe').title,'سرورها و نقش نمایندگی');
  d.querySelector('.setup-step-link').click();
  assert.equal(d.querySelector('.step.current h2').textContent,'سرورها');
  assert.equal(d.getElementById('setupServers').hidden,true);
  assert.deepEqual(x.errors,[]);
 }finally{x.dom.window.close()}
});
