// Run with: node tests/admin_api_paths.cjs (frontend dependencies installed).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('../frontend/node_modules/typescript');
const root = require('node:path').join(__dirname, '..', 'frontend/lib');
const window = { location: { pathname: '/private-admin/admin/servers', origin: 'https://example.test' } };
const document = { cookie: 'dbot_csrf_token=verified-token' };
let calls = [], status = 200;
const fetch = async (path, options) => {
  calls.push({path, options});
  return {status, ok: status === 200, type: 'basic', redirected: false, url: 'https://example.test'+path,
    headers: {get: () => 'application/json'}, json: async () => status === 200 ? {ok:true} : {detail: status === 403 ? 'CSRF validation failed' : 'Admin session expired'}};
};
function load(name) {
 const exports = {};
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(root+'/'+name+'.ts','utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,
 {exports, require: () => load('web-path'), window, document, fetch, FormData, URL, Error});
 return exports;
}
(async () => {
 const {publicWebPath} = load('web-path');
 assert.equal(publicWebPath('/admin/settings?x=1'), '/private-admin/admin/settings?x=1');
 assert.equal(publicWebPath('/private-admin/admin/settings'), '/private-admin/admin/settings');
 assert.equal(publicWebPath('/api/miniapp/me'), '/api/miniapp/me');
 assert.equal(publicWebPath('https://other.test/admin'), 'https://other.test/admin');
 const api = load('api');
 for(const pathname of ['/private-admin/admin/servers','/admin/servers','/adminportal/admin/settings']) {
   window.location.pathname = pathname;
   const prefix = pathname === '/admin/servers' ? '' : '/'+pathname.split('/')[1];
   for(const invoke of [() => api.fetchJson('/admin/api/v2/resources'), () => api.submitForm('/admin/servers/save',{username:'owner'}), () => api.getAction('/admin/servers/1/refresh')]) {
     status = 200; await invoke();
     const call = calls.at(-1);
     assert.equal(call.path.startsWith(prefix+'/admin/'), true);
     assert.equal(call.options.headers['X-CSRF-Token'], 'verified-token');
     assert.equal(call.options.credentials, 'include');
     if(call.options.method === 'POST') assert.equal(call.options.redirect, 'manual');
     status = 403; await assert.rejects(invoke, /CSRF validation failed/);
     status = 401; await assert.rejects(invoke, /AUTH_REQUIRED/);
   }
 }
 status=307; await assert.rejects(() => api.submitForm('/admin/settings',{}), /AUTH_REQUIRED/);
 console.log('Passed: prefixed/bare paths, all three API helpers, CSRF headers, 403 preserves login, 401 requires login, POST redirect protection.');
})().catch(e=>{console.error(e);process.exit(1)});
