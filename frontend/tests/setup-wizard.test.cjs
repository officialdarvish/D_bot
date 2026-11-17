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
  assert.equal(x.document.getElementById('setupError').textContent,'');assert.deepEqual(x.errors,[]);
 }finally{x.dom.window.close()}
});
test('HTML response shows a clear error and never retries an ambiguous add',async()=>{
 const x=environment(()=>({...response(null,200,'text/html'),json:async()=>{throw new SyntaxError('Unexpected token <')}}));try{
  x.document.getElementById('setupAddServer').click();await tick();
  assert.match(x.document.getElementById('setupError').textContent,/non-JSON page/);
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
  assert.match(x.document.querySelector('.step.current h2').textContent,/Servers/);
  assert.equal(x.calls[0].url,'/private/setup/progress');assert.equal(x.calls.length,1);
 }finally{x.dom.window.close()}
});
