const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require('typescript');
require.extensions['.ts']=(mod,name)=>mod._compile(ts.transpileModule(fs.readFileSync(name,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,name);
const {errorMessage}=require('../lib/error-message.ts');
const api=require('../lib/api.ts');
const invalid={detail:[{loc:['body','telegram_id'],msg:'Input should be a valid integer',type:'int_parsing',input:'secret-input'},{loc:['body','days'],msg:'Field required',type:'missing'}]};

test('FastAPI 422 arrays name each invalid field without echoing raw input',()=>{
 const result=errorMessage(invalid,'fallback','en');
 assert.match(result,/Telegram numeric ID: Enter a whole number/);
 assert.match(result,/Remaining days: This field is required/);
 assert(!result.includes('[object'));assert(!result.includes('secret-input'));
 assert.match(errorMessage(invalid,'fallback','fa'),/آیدی عددی تلگرام: عدد صحیح/);
});
test('nested errors, string errors and Error instances remain readable',()=>{
 for(const value of [{detail:{message:'Choose a server'}},{message:{detail:'Choose a server'}},{error:{message:'Choose a server'}},new Error('Choose a server'),'Choose a server'])assert.equal(errorMessage(value),'Choose a server');
});
test('unknown payloads cannot leak submitted data or stringify objects',()=>{
 const value={input:{password:'do-not-show'},stack:'internal stack'};value.error=value;
 for(const item of [value,{},null,42,'[object Object]',{detail:[{},{}]}])assert.equal(errorMessage(item,'Safe fallback'),'Safe fallback');
});
test('all three shared API clients use the same structured error contract',async()=>{
 const original=global.fetch;
 try{
  global.fetch=async()=>new Response(JSON.stringify(invalid),{status:422,headers:{'content-type':'application/json'}});
  for(const call of [()=>api.fetchJson('/admin/api/v2/resellers'),()=>api.submitForm('/admin/resellers/add',{telegram_id:'bad'}),()=>api.getAction('/admin/action')])await assert.rejects(call(),e=>e.message.includes('Telegram numeric ID')&&!e.message.includes('[object'));
 }finally{global.fetch=original;}
});
test('authentication sentinel, HTML and invalid JSON responses stay bounded',async()=>{
 const original=global.fetch;
 try{
  global.fetch=async()=>new Response('{}',{status:401,headers:{'content-type':'application/json'}});
  await assert.rejects(api.submitForm('/admin/resellers/add',{}),{message:'AUTH_REQUIRED'});
  global.fetch=async()=>new Response('<html>private</html>',{status:500,headers:{'content-type':'text/html'}});
  await assert.rejects(api.fetchJson('/admin/x'),e=>!e.message.includes('<html>'));
  global.fetch=async()=>new Response('bad json',{status:500,headers:{'content-type':'application/json'}});
  await assert.rejects(api.getAction('/admin/x'),{message:'Action failed: 500'});
 }finally{global.fetch=original;}
});
