/* Darvish Bridge: zero-build Telegram Mini App, RTL Persian UI.
   All privileged operations are re-authorized on the backend. */
(() => {
  'use strict';
  const telegram = window.Telegram?.WebApp;
  const initData = telegram?.initData || '';
  const $ = (selector) => document.querySelector(selector);
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const state = {me:null, admin:null, seller:null, selectedMerchant:null, tab:'home', photoUrl:null};
  const scales = {IRT:0,USDT:6,TON:9,USD:2,EUR:2,UNIT:2};
  const statusMap = {pending:'در انتظار',approved:'تأییدشده',rejected:'ردشده',paid:'پرداخت‌شده',requested:'درخواست‌شده',
    awaiting_receipt:'در انتظار رسید',receipt_submitted:'نیازمند بررسی',fulfillment_pending:'در انتظار تحویل',
    fulfilled:'تحویل‌شده',delivery_failed:'خطای تحویل',refunded:'برگشت وجه',suspended:'تعلیق‌شده',open:'باز',resolved:'بررسی‌شده'};
  const niceStatus = s => `<span class="tag ${['approved','paid','fulfilled','resolved'].includes(s)?'good':['rejected','delivery_failed','refunded','suspended'].includes(s)?'bad':'warn'}">${escape(statusMap[s] || s)}</span>`;
  const date = d => d ? new Date(d).toLocaleString('fa-IR') : '—';
  function amount(value, currency){
    const scale=scales[currency] ?? 0;
    let n=BigInt(value ?? 0), negative=n<0n;
    if(negative)n=-n;
    const factor=10n**BigInt(scale), int=n/factor, decimal=(n%factor).toString().padStart(scale,'0').replace(/0+$/,'');
    return `${negative?'-':''}${int.toLocaleString('fa-IR')}${decimal?'٫'+decimal:''} ${currency==='IRT'?'تومان':escape(currency)}`;
  }
  function toMinor(value,currency){
    const scale=scales[currency];
    if(scale===undefined)throw Error('ارز نامعتبر است');
    if(!/^\d+(\.\d+)?$/.test(value))throw Error('مبلغ را با اعداد انگلیسی وارد کنید');
    const [whole,frac='']=value.split('.');
    if(frac.length>scale)throw Error('اعشار مبلغ بیش از دقت ارز است');
    const n=BigInt(whole)*10n**BigInt(scale)+BigInt((frac+'0'.repeat(scale)).slice(0,scale)||'0');
    if(n<=0n||n>BigInt(Number.MAX_SAFE_INTEGER))throw Error('مبلغ خارج از محدوده است');
    return Number(n);
  }
  const currencyOptions = Object.keys(scales).map(c => `<option value="${c}">${c==='IRT'?'تومان (IRT)':c}</option>`).join('');
  const btn = (text, action, id='', kind='secondary', extra='') => `<button class="button ${kind} small" data-action="${escape(action)}" data-id="${escape(id)}" ${extra}>${escape(text)}</button>`;
  const none = (title,desc='موردی برای نمایش وجود ندارد') => `<div class="empty"><strong>${escape(title)}</strong>${escape(desc)}</div>`;
  function title(name, desc=''){return `<div class="section-title"><div><h2>${escape(name)}</h2>${desc?`<p>${escape(desc)}</p>`:''}</div></div>`;}
  function table(headers,rows){
    if(!rows.length)return none('اطلاعاتی ثبت نشده است');
    return `<div class="table-wrap"><table><thead><tr>${headers.map(s=>`<th>${escape(s)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(cell=>`<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  }
  function notify(message,error=false){
    const el=$('#notice');el.textContent=message;el.classList.remove('hidden');el.classList.toggle('error',error);
    clearTimeout(notify.timer);notify.timer=setTimeout(()=>el.classList.add('hidden'),6500);
  }
  async function api(path,method='GET',data){
    const options={method,headers:{'X-Telegram-Init-Data':initData}};
    if(data!==undefined){options.headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
    let response;
    try { response=await fetch('/api/v1'+path,options); }catch{throw Error('ارتباط با سرور برقرار نشد');}
    let body=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:'درخواست ناموفق بود');
    return body;
  }
  function modal(name,html){$('#modal-title').textContent=name;$('#modal-body').innerHTML=html;$('#modal').classList.remove('hidden');}
  function closeModal(){
    $('#modal').classList.add('hidden');$('#modal-body').innerHTML='';
    if(state.photoUrl){URL.revokeObjectURL(state.photoUrl);state.photoUrl=null;}
  }
  $('#modal-close').addEventListener('click',closeModal);
  $('#modal').addEventListener('click',event=>{if(event.target.id==='modal')closeModal();});
  function metric(label,value,sub=''){return `<article class="card"><div class="metric-label">${escape(label)}</div><div class="metric-value">${escape(value)}</div><div class="metric-note">${escape(sub)}</div></article>`;}
  function tabs(){
    let items = [{id:'home',label:'خانه'}];
    if(state.me.is_admin) items.push({id:'orders',label:'سفارش‌ها'},{id:'merchants',label:'فروشندگان'},{id:'accounts',label:'حساب‌های دریافت'},{id:'settlements',label:'تسویه‌ها'},{id:'disputes',label:'اختلافات'},{id:'audit',label:'رویدادها'});
    items.push({id:'seller',label:'پنل فروشنده'});
    $('#nav').innerHTML = items.map(x=>`<button class="tab ${state.tab===x.id?'active':''}" data-tab="${x.id}">${x.label}</button>`).join('');
  }
  function adminHome(){
    const s=state.admin; if(!s)return none('در حال بارگذاری');
    const pending=s.orders.filter(o=>o.status==='receipt_submitted');
    return `<div class="grid">${metric('تعداد فروشندگان',s.totals.merchants)}${metric('رسیدهای در انتظار',s.totals.pending_receipts)}${metric('تسویه‌های باز',s.totals.pending_settlements)}${metric('کل سفارش‌های بارگذاری‌شده',s.orders.length,'حداکثر ۱۰۰ سفارش اخیر')}</div>`+
      title('رسیدهای نیازمند بررسی','تأیید فقط پس از مشاهده واریز واقعی')+
      orderTable(pending.slice(0,15))+
      title('درخواست‌های اخیر تسویه')+settlementTable(s.settlements.filter(x=>x.status==='requested'||x.status==='approved').slice(0,10));
  }
  function orderTable(orders){return table(['شناسه','محصول','مبلغ','وضعیت','تاریخ','عملیات'],orders.map(o=>[
    `<span class="latin">${escape(o.id.slice(0,8))}…</span>`,escape(o.product_title),amount(o.amount_minor,o.currency),niceStatus(o.status),date(o.created_at),
    o.status==='receipt_submitted'?`<div class="actions">${btn('مشاهده رسید','photo',o.id)}${btn('تأیید','approve',o.id,'secondary')}${btn('رد','reject',o.id,'danger')}</div>`:
    ['fulfillment_pending','delivery_failed'].includes(o.status)?`<div class="actions">${btn('تلاش مجدد تحویل','retryDelivery',o.id)}${btn('بازگشت وجه','refund',o.id,'danger')}</div>`:
    o.status==='fulfilled'?`<div class="actions">${btn('بازگشت وجه','refund',o.id,'danger')}</div>`:`<span class="micro">${escape(o.external_order_id)}</span>`]));}
  function settlementTable(settlements, owner=false){return table(['شناسه','مبلغ','مقصد','وضعیت','تاریخ','عملیات'],settlements.map(s=>[
    `<span class="latin">${escape(s.id.slice(0,8))}…</span>`,amount(s.amount_minor,s.currency),`<span class="long">${escape(s.destination)}</span>`,niceStatus(s.status),date(s.created_at),owner?'—':
    `<div class="actions">${s.status==='requested'?btn('تأیید درخواست','settleApprove',s.id):''}${['requested','approved'].includes(s.status)?btn('رد','settleReject',s.id,'danger'):''}${s.status==='approved'?btn('ثبت انتقال','settlePaid',s.id):''}</div>`]));}
  function merchantTable(){const s=state.admin;return title('فروشندگان ثبت‌شده','فقط مدیر اصلی می‌تواند درخواست‌های جدید را تأیید کند')+
    table(['فروشنده','شناسه','کارمزد','وضعیت','عملیات'],s.merchants.map(m=>[
      escape(m.name),`<span class="latin">${escape(m.id.slice(0,8))}…</span>`,`${m.fee_bps/100}٪`,niceStatus(m.status),
      m.status==='pending'?`<div class="actions">${btn('تأیید','merchantApprove',m.id)}${btn('رد','merchantReject',m.id,'danger')}</div>`:
      ['approved','suspended'].includes(m.status)?`<div class="actions">${btn('تنظیم کارمزد','merchantFee',m.id)}${btn(m.status==='approved'?'تعلیق':'فعال‌سازی','merchantStatus',m.id,m.status==='approved'?'danger':'secondary')}</div>`:'—' ]));}
  function accounts(){const s=state.admin;return `<div class="notice-note">حساب‌های دریافت فقط برای معاملات مجاز ثبت شوند. انتخاب تصادفی از حساب‌ها، جایگزین رعایت مقررات و تطبیق دریافت واقعی نیست.</div>`+
    `<div class="card">${title('افزودن مقصد دریافت')}<form data-form="addAccount" class="form-grid">
      <div class="field"><label>واحد دریافت</label><select name="currency">${currencyOptions}</select></div>
      <div class="field"><label>عنوان مقصد</label><input name="label" required maxlength="120" placeholder="کیف پول رسمی مجموعه"></div>
      <div class="field wide"><label>اطلاعات نمایش به خریدار</label><textarea name="instructions" required minlength="5" maxlength="2000" placeholder="نشانی مقصد و دستورالعمل انتقال"></textarea></div>
      <button class="button wide">ثبت مقصد دریافت</button></form></div>`+
    title('مقصدهای تعریف‌شده')+table(['عنوان','ارز','اطلاعات','وضعیت','عملیات'],s.accounts.map(a=>[
      escape(a.label),escape(a.currency),`<span class="long">${escape(a.instructions)}</span>`,niceStatus(a.active?'approved':'rejected'),btn(a.active?'غیرفعال‌کردن':'فعال‌کردن','toggleAccount',a.id)
    ]));}
  function disputes(){return title('اختلافات ثبت‌شده')+table(['سفارش','شرح','وضعیت','عملیات'],state.admin.disputes.map(d=>[
    `<span class="latin">${escape(d.order_id.slice(0,8))}…</span>`,escape(d.reason),niceStatus(d.status),
    d.status==='open'?btn('ثبت نتیجه','disputeResolve',d.id):escape(d.resolution||'—')]));}
  function audit(){return title('رویدادهای حسابرسی','۱۰۰ رویداد آخر')+`<div class="card" id="audit-content">برای بارگذاری رویدادها روی دکمه زیر کلیک کنید. ${btn('بارگذاری','loadAudit')}</div>`;}
  function seller(){
    const merchants=state.me.merchants;
    const choose=merchants.length?`<div class="field" style="margin-bottom:18px"><label>فروشنده فعلی</label><select id="merchant-select">${merchants.map(m=>`<option value="${escape(m.id)}" ${m.id===state.selectedMerchant?'selected':''}>${escape(m.name)} | ${escape(statusMap[m.status]||m.status)}</option>`).join('')}</select></div>`:'';
    if(!merchants.length)return `<div class="grid two"><div class="card"><h2>ثبت فروشنده جدید</h2><p class="muted">برای دریافت دسترسی و اتصال ربات، ابتدا درخواست فروشندگی ثبت کنید.</p>
      <form data-form="register" class="stack"><div class="field"><label>نام فروشگاه</label><input name="name" required minlength="2" maxlength="120" placeholder="نام فروشگاه شما"></div><button class="button">ارسال درخواست</button></form></div></div>`;
    const s=state.seller;
    if(!s)return choose+none('در حال بارگذاری اطلاعات فروشنده');
    return choose+`<div class="notice-note">${s.merchant.status==='approved'?'حساب فروشنده فعال است. اطلاعات اتصال محرمانه را در اختیار دیگران قرار ندهید.':'حساب فروشنده هنوز تأیید نشده است و امکان اتصال ربات یا تسویه وجود ندارد.'}</div>`+
      title('موجودی‌های ثبت‌شده')+(Object.keys(s.balances).length?`<div class="grid two">${Object.entries(s.balances).map(([c,b])=>`<article class="balance-item"><strong>${escape(c)}</strong><div>قابل تسویه</div><div class="amount">${amount(b.seller_available||0,c)}</div><div class="muted">رزروشده: ${amount(b.seller_reserved||0,c)}</div></article>`).join('')}</div>`:none('موجودی وجود ندارد','هنوز سفارش تأییدشده‌ای ثبت نشده است.'))+
      `<div class="grid two" style="margin-top:18px"><div class="card">${title('ثبت درخواست تسویه')}<form data-form="settle" class="stack">
        <div class="field"><label>مبلغ</label><input required name="amount" class="ltr" placeholder="10.50" inputmode="decimal"></div>
        <div class="field"><label>واحد تسویه</label><select name="currency">${currencyOptions}</select></div>
        <div class="field"><label>مقصد تسویه</label><input required minlength="5" name="destination" placeholder="آدرس یا مشخصات حساب مقصد"></div>
        <button class="button" ${s.merchant.status==='approved'?'':'disabled'}>درخواست تسویه</button></form></div>
      <div class="card">${title('اتصال ربات جدید')}<form data-form="newBot" class="stack">
        <div class="field"><label>نام اتصال</label><input name="label" required maxlength="120" placeholder="D Bot فروشگاه"></div>
        <div class="field"><label>نشانی وب‌هوک HTTPS (اختیاری)</label><input class="ltr" name="webhook_url" placeholder="https://merchant.example.com/hooks/darvish"></div>
        <p class="hint">اگر وب‌هوک ثبت می‌کنید، دامنه باید از قبل در فهرست مجاز سرور ثبت شده باشد.</p>
        <button class="button" ${s.merchant.status==='approved'?'':'disabled'}>ایجاد کلید اتصال</button></form></div></div>`+
      title('ربات‌های متصل')+table(['عنوان','شناسه','وب‌هوک','وضعیت','عملیات'],s.bots.map(b=>[
        escape(b.label),`<span class="latin">${escape(b.id.slice(0,8))}…</span>`,escape(b.webhook_url||'بدون وب‌هوک'),niceStatus(b.active?'approved':'rejected'),b.active?btn('لغو کلید','revokeBot',b.id,'danger'):'—']))+
      title('سفارش‌های فروشنده')+table(['شناسه','محصول','مبلغ','وضعیت'],s.orders.map(o=>[
        `<span class="latin">${escape(o.id.slice(0,8))}…</span>`,escape(o.product_title),amount(o.amount_minor,o.currency),niceStatus(o.status)]))+
      title('تاریخچه تسویه')+settlementTable(s.settlements,true);
  }
  function render(){
    const admin=state.me.is_admin;
    const names={home:'داشبورد',orders:'سفارش‌ها',merchants:'فروشندگان',accounts:'مقصدهای دریافت',settlements:'تسویه حساب‌ها',disputes:'اختلافات',audit:'گزارش رویدادها',seller:'حساب فروشنده'};
    $('#greeting').textContent=names[state.tab]||'داشبورد';
    tabs();
    let html='';
    switch(state.tab){
      case 'home': html=admin?adminHome():seller();break;
      case 'orders': html=admin?title('همه سفارش‌ها')+orderTable(state.admin.orders):seller();break;
      case 'merchants': html=admin?merchantTable():seller();break;
      case 'accounts': html=admin?accounts():seller();break;
      case 'settlements': html=admin?title('درخواست‌های تسویه')+settlementTable(state.admin.settlements):seller();break;
      case 'disputes': html=admin?disputes():seller();break;
      case 'audit': html=admin?audit():seller();break;
      case 'seller': html=seller();break;
    }
    $('#content').innerHTML=html;
  }
  async function refresh(){
    state.me=await api('/me');
    if(!state.selectedMerchant&&state.me.merchants.length)state.selectedMerchant=state.me.merchants[0].id;
    if(state.me.is_admin)state.admin=await api('/admin/overview');
    if(state.selectedMerchant)state.seller=await api(`/merchants/${state.selectedMerchant}/dashboard`);
    $('#profile').textContent=(state.me.user.first_name||'د').slice(0,1);
    $('#auth-warning').classList.add('hidden');$('#app').classList.remove('hidden');render();
  }
  async function action(kind,id){
    switch(kind){
      case 'photo': {
        const response=await fetch(`/api/v1/admin/orders/${encodeURIComponent(id)}/receipt-photo`,{headers:{'X-Telegram-Init-Data':initData}});
        if(!response.ok)throw Error('دریافت تصویر رسید امکان‌پذیر نبود');
        state.photoUrl=URL.createObjectURL(await response.blob());
        modal('تصویر رسید',`<div class="notice-note">برای تأیید دریافت واقعی، فقط به تصویر اعتماد نکنید. ابتدا حساب مقصد را بررسی کنید.</div><img class="receipt-image" src="${state.photoUrl}" alt="رسید ارسالی خریدار">`);return;
      }
      case 'approve':
        if(!confirm('آیا دریافت واقعی مبلغ را مستقل از عکس رسید بررسی و تأیید کرده‌اید؟'))return;
        await api(`/admin/orders/${id}/approve`,'POST',{verified_real_transfer:true,note:'دریافت واقعی توسط مدیر تأیید شد'});break;
      case 'reject': {
        const note=prompt('علت رد رسید را وارد کنید:','واریز قابل تأیید نبود');if(note===null)return;
        await api(`/admin/orders/${id}/reject`,'POST',{verified_real_transfer:false,note});break;
      }
      case 'merchantApprove':
        await api(`/admin/merchants/${id}/review`,'POST',{approved:true,fee_bps:500});break;
      case 'merchantFee': {
        const m=state.admin.merchants.find(x=>x.id===id);
        const input=prompt('کارمزد جدید به درصد (مثلاً 5 یا 2.5):',String(m.fee_bps/100));
        if(input===null)return;
        const percent=Number(input);
        if(!Number.isFinite(percent)||percent<0||percent>30||!Number.isInteger(percent*100))throw Error('درصد کارمزد معتبر نیست');
        await api(`/admin/merchants/${id}/settings`,'POST',{status:m.status,fee_bps:Math.round(percent*100)});break;
      }
      case 'merchantStatus': {
        const m=state.admin.merchants.find(x=>x.id===id);
        const next=m.status==='approved'?'suspended':'approved';
        if(!confirm(`وضعیت این فروشنده به ${next} تغییر کند؟`))return;
        await api(`/admin/merchants/${id}/settings`,'POST',{status:next,fee_bps:m.fee_bps});break;
      }
      case 'merchantReject':
        if(!confirm('درخواست فروشنده رد شود؟'))return;
        await api(`/admin/merchants/${id}/review`,'POST',{approved:false,fee_bps:500});break;
      case 'toggleAccount': await api(`/admin/accounts/${id}/toggle`,'POST');break;
      case 'settleApprove': await api(`/admin/settlements/${id}/review`,'POST',{action:'approve'});break;
      case 'settleReject':
        if(!confirm('این درخواست رد و مبلغ رزروشده آزاد شود؟'))return;
        await api(`/admin/settlements/${id}/review`,'POST',{action:'reject'});break;
      case 'settlePaid': {
        const ref=prompt('شناسه انتقال واقعی انجام‌شده را وارد کنید:');if(!ref)return;
        await api(`/admin/settlements/${id}/review`,'POST',{action:'paid',payout_reference:ref});break;
      }
      case 'retryDelivery':
        await api(`/admin/orders/${id}/retry-delivery`,'POST');break;
      case 'refund': {
        if(!confirm('آیا بازگشت واقعی وجه انجام شده است؟ این عملیات موجودی فروشنده را اصلاح می‌کند.'))return;
        const ref=prompt('شناسه انتقال برگشت واقعی:');if(!ref)return;
        const reason=prompt('علت بازگشت وجه:','عدم تحویل / توافق طرفین');if(!reason)return;
        await api(`/admin/orders/${id}/refund`,'POST',{verified_actual_refund:true,payout_reference:ref,reason});break;
      }
      case 'revokeBot':
        if(!confirm('این کلید اتصال فوراً باطل شود؟'))return;
        await api(`/merchants/${state.selectedMerchant}/bots/${id}/revoke`,'POST');break;
      case 'disputeResolve': {
        const resolution=prompt('نتیجه بررسی اختلاف را وارد کنید:');if(!resolution)return;
        await api(`/admin/disputes/${id}/resolve`,'POST',{resolution});break;
      }
      case 'loadAudit': {
        const rows=await api('/admin/audit');
        $('#audit-content').innerHTML=table(['زمان','کاربر','عملیات','شناسه'],rows.map(a=>[date(a.created_at),escape(a.actor),escape(a.action),`<span class="latin">${escape(a.target_id.slice(0,8))}</span>`]));return;
      }
      default:return;
    }
    notify('عملیات ثبت شد.');await refresh();
  }
  async function formSubmit(form){
    const kind=form.dataset.form, fd=new FormData(form);
    const val=name=>String(fd.get(name)||'').trim();
    if(kind==='register'){
      await api('/merchants','POST',{name:val('name')});
    }else if(kind==='addAccount'){
      await api('/admin/accounts','POST',{currency:val('currency'),label:val('label'),instructions:val('instructions')});
    }else if(kind==='settle'){
      await api(`/merchants/${state.selectedMerchant}/settlements`,'POST',{amount_minor:toMinor(val('amount'),val('currency')),currency:val('currency'),destination:val('destination')});
    }else if(kind==='newBot'){
      const b=await api(`/merchants/${state.selectedMerchant}/bots`,'POST',{label:val('label'),webhook_url:val('webhook_url')||null});
      modal('کلیدهای اتصال — فقط یک بار',`<p class="notice-note">این کلیدها فقط همین بار نمایش داده می‌شوند. آن‌ها را در فایل امن محیط سرور ذخیره کنید؛ در تلگرام برای کسی ارسال نکنید.</p>
        <h3>کلید اتصال API</h3><div class="secret">${escape(b.api_key_once)}</div><h3>رمز امضای وب‌هوک</h3><div class="secret">${escape(b.webhook_secret_once)}</div><p class="hint">شناسه اتصال: ${escape(b.bot_id)}</p>`);
    }
    notify('اطلاعات با موفقیت ثبت شد.');await refresh();
  }
  document.addEventListener('click',async event=>{
    const tab=event.target.closest('[data-tab]');
    if(tab){state.tab=tab.dataset.tab;render();return;}
    const b=event.target.closest('[data-action]');
    if(!b)return;
    b.disabled=true;
    try{await action(b.dataset.action,b.dataset.id);}catch(err){notify(err.message,true);}finally{b.disabled=false;}
  });
  document.addEventListener('change',async event=>{
    if(event.target.id!=='merchant-select')return;
    state.selectedMerchant=event.target.value;
    try{state.seller=await api(`/merchants/${state.selectedMerchant}/dashboard`);render();}catch(err){notify(err.message,true);}
  });
  document.addEventListener('submit',async event=>{
    const form=event.target.closest('[data-form]');if(!form)return;
    event.preventDefault();const button=form.querySelector('button[type=submit],button:not([type])');if(button)button.disabled=true;
    try{await formSubmit(form);}catch(err){notify(err.message,true);}finally{if(button)button.disabled=false;}
  });
  telegram?.ready();telegram?.expand();
  if(!initData){$('#auth-warning').classList.remove('hidden');return;}
  refresh().catch(err=>{$('#auth-warning').classList.remove('hidden');notify(err.message,true);});
})();
