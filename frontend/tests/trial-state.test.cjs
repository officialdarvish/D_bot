const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const ts=require('typescript');
require.extensions['.ts']=(mod,name)=>mod._compile(ts.transpileModule(fs.readFileSync(name,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,name);
const {canRequestTrial,trialServices}=require('../lib/miniapp-trial-state.ts');
const info={used:false,can_request:true,can_repeat:false,server_count:2,services:[]};
const op=(status,services=[])=>({id:1,status,result:{services}});
test('normal user cannot request again while completion refresh is pending',()=>{
 assert(canRequestTrial(info,null));
 assert(!canRequestTrial(info,op('done')));
 assert(!canRequestTrial({...info,used:true},null));
});
test('admin can start a new test after completion but never while running',()=>{
 const admin={...info,can_repeat:true};
 assert(canRequestTrial(admin,op('done')));
 for(const status of ['queued','processing'])assert(!canRequestTrial(admin,op(status)));
});
test('failed batch can retry only after server confirms quota is free',()=>{
 assert(canRequestTrial(info,op('failed')));
 assert(!canRequestTrial({...info,can_request:false},op('failed')));
 assert(!canRequestTrial({...info,server_count:0},op('failed')));
 assert(!canRequestTrial(null,op('failed')));
});
test('bot-created and native trial results share one deduplicated delivery list',()=>{
 const botTrial={id:10,username:'test_bot',server:'A'};
 const old={id:11,username:'test_native',server:'B',active:false};
 const fresh={...old,active:true};
 assert.deepEqual(trialServices({...info,services:[botTrial,old]},op('done',[fresh])),[botTrial,fresh]);
 assert.deepEqual(trialServices(null,null),[]);
});
