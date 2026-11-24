'use client';

import { useEffect, useState } from 'react';
import { Bot, LockKeyhole, Plus, Save, ShieldCheck, Users, X } from 'lucide-react';
import { fetchJson, submitForm } from '@/lib/api';
import { useSettingsLanguage } from '@/lib/settings-language';
import { MiniAppCheck } from './miniapp-check';

const switches = [
  ['enabled', 'Enable Mini App', 'فعال بودن مینی‌اپ'],
  ['animations', 'Animate the background', 'انیمیشن پس‌زمینه'],
  ['fullscreen', 'Fullscreen on supported Telegram clients', 'تمام‌صفحه در نسخه‌های پشتیبانی‌شدهٔ تلگرام'],
  ['show_buy', 'Purchase subscriptions', 'خرید اشتراک'],
  ['show_wallet', 'Wallet', 'کیف پول'],
  ['show_services', 'My configs', 'کانفیگ‌های من'],
  ['show_support', 'Direct support chat', 'ارتباط مستقیم پشتیبانی'],
  ['show_trial', 'Show the trial account button', 'نمایش دکمهٔ اکانت تست'],
  ['show_tutorials', 'Show the tutorials button', 'نمایش دکمهٔ آموزش‌ها'],
  ['show_rules', 'Show the rules button', 'نمایش دکمهٔ قوانین'],
  ['reseller_enabled', 'Reseller workspace', 'محیط نمایندگی'],
  ['reseller_requests', 'Allow reseller requests in the bot and Mini App', 'دریافت درخواست نمایندگی در ربات و مینی‌اپ'],
] as const;
type Flag = typeof switches[number][0];
type Config = Record<Flag, boolean> & {
  welcome: string;
  support_username: string;
  links: { label: string; url: string }[];
};
export type MiniAppSettingsProps = {
  reloadKey: number;
  setAuthRequired: (value: boolean) => void;
  show: (message: string, good?: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
};

function editableConfig(config: Config): Config {
  const flags = Object.fromEntries(switches.map(([key]) => [key, config[key]])) as Record<Flag, boolean>;
  return { ...flags, welcome: config.welcome, support_username: config.support_username, links: config.links };
}

export function MiniAppSettings({ reloadKey, setAuthRequired, show, onDirtyChange }: MiniAppSettingsProps) {
  const { s, language, failure } = useSettingsLanguage();
  const [draft, setDraft] = useState<Config | null>(null);
  const [saved, setSaved] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const dirty = !!draft && JSON.stringify(draft) !== saved;
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    fetchJson<{ config: Config }>('/admin/api/v2/miniapp', controller.signal).then(result => {
      if (controller.signal.aborted) return;
      const value = editableConfig(result.config);
      setDraft(value);
      setSaved(JSON.stringify(value));
    }).catch((cause: Error) => {
      if (controller.signal.aborted) return;
      if (cause.message === 'AUTH_REQUIRED') setAuthRequired(true);
      setError(cause);
    });
    return () => controller.abort();
  }, [reloadKey, retry, setAuthRequired]);

  async function save() {
    if (!draft || !dirty || busy) return;
    setBusy(true);
    const submitted = JSON.stringify(draft);
    try {
      const result = await submitForm('/admin/miniapp/save', { config_json: submitted });
      setSaved(submitted);
      show(result.menu_sync_pending
        ? s('Settings saved. Telegram will retry updating the launcher.', 'تنظیمات ذخیره شد. به‌روزرسانی دکمهٔ تلگرام دوباره تلاش می‌شود.')
        : s('Mini App settings saved.', 'تنظیمات مینی‌اپ ذخیره شد.'), true);
    } catch (cause) {
      if (cause instanceof Error && cause.message === 'AUTH_REQUIRED') setAuthRequired(true);
      show(failure(cause), false);
    } finally {
      setBusy(false);
    }
  }

  if (!draft) return <section className="panel" data-no-i18n="true">
    <p role={error ? 'alert' : 'status'}>{error ? failure(error) : s('Loading Mini App settings…', 'در حال دریافت تنظیمات مینی‌اپ…')}</p>
    {error && <button type="button" className="btn" onClick={() => setRetry(value => value + 1)}>{s('Retry', 'تلاش دوباره')}</button>}
  </section>;

  return <form className="cj-miniapp-settings" data-no-i18n="true" dir={language === 'fa' ? 'rtl' : 'ltr'} onSubmit={event => { event.preventDefault(); void save(); }}>
    <section className="panel">
      <header className="cj-section-head"><div><h2><Bot size={20}/> {s('Mini App settings', 'تنظیمات مینی‌اپ')}</h2></div><span className={'badge ' + (draft.enabled ? 'green' : 'red')}>{draft.enabled ? s('Enabled', 'فعال') : s('Disabled', 'غیرفعال')}</span></header>
      <div className="cj-miniapp-fields">
        <label className="form-field"><span>{s('Home subtitle', 'متن زیر عنوان خانه')}</span><input value={draft.welcome} maxLength={180} dir="auto" disabled={busy} onChange={event => setDraft({ ...draft, welcome: event.target.value })}/></label>
        <label className="form-field"><span>{s('Telegram support username', 'نام کاربری پشتیبانی تلگرام')}</span><input value={draft.support_username} maxLength={60} dir="ltr" placeholder="@support" disabled={busy} onChange={event => setDraft({ ...draft, support_username: event.target.value })}/></label>
      </div>
      <p className="cj-miniapp-brand-note muted"><LockKeyhole size={14}/>{s('The Mini App and Telegram launcher use the D BOT brand.', 'مینی‌اپ و دکمهٔ کنار چت با برند D BOT نمایش داده می‌شوند.')}</p>
      <div className="cj-miniapp-fields">{switches.map(([key, en, fa]) => <MiniAppCheck key={key} checked={draft[key]} disabled={busy} onChange={checked => setDraft({ ...draft, [key]: checked })}>{s(en, fa)}</MiniAppCheck>)}</div>
    </section>
    <section className="panel">
      <header className="cj-section-head"><div><h3>{s('Shortcuts', 'لینک‌های میان‌بر')}</h3></div><button type="button" className="btn" disabled={busy || draft.links.length >= 6} onClick={() => setDraft({ ...draft, links: [...draft.links, { label: '', url: '' }] })}><Plus size={16}/>{s('Add link', 'افزودن لینک')}</button></header>
      {draft.links.map((link, index) => <div className="cj-miniapp-shortcut" key={index}>
        <label className="form-field"><span>{s('Link title', 'عنوان لینک')} {index + 1}</span><input required maxLength={50} dir="auto" value={link.label} disabled={busy} onChange={event => setDraft({ ...draft, links: draft.links.map((row, i) => i === index ? { ...row, label: event.target.value } : row) })}/></label>
        <label className="form-field"><span>{s('HTTPS URL', 'نشانی HTTPS')} {index + 1}</span><input type="url" required maxLength={1000} dir="ltr" placeholder="https://" value={link.url} disabled={busy} onChange={event => setDraft({ ...draft, links: draft.links.map((row, i) => i === index ? { ...row, url: event.target.value } : row) })}/></label>
        <button type="button" className="btn danger" aria-label={s('Remove shortcut', 'حذف لینک میان‌بر')} disabled={busy} onClick={() => setDraft({ ...draft, links: draft.links.filter((_, i) => i !== index) })}><X size={16}/></button>
      </div>)}
      <div className="card-actions"><button type="submit" className="btn primary" disabled={!dirty || busy}><Save size={16}/>{busy ? s('Saving…', 'در حال ذخیره…') : s('Save Mini App settings', 'ذخیرهٔ تنظیمات مینی‌اپ')}</button></div>
    </section>
  </form>;
}

export function AccessRuleCards({map,show,setAuthRequired}:any){
 const {s,failure}=useSettingsLanguage();
 const [rules,setRules]=useState(String(map.rules_text||'')),[rulesOn,setRulesOn]=useState(map.rules_enabled==='1');
 const [joinOn,setJoinOn]=useState(map.force_join_enabled==='1'),[channel,setChannel]=useState(String(map.channel_url||'')),[busy,setBusy]=useState('');
 async function save(kind:string){
  setBusy(kind);
  try{await submitForm('/admin/settings/'+kind,kind==='rules'?{enabled:rulesOn?'1':'0',rules_text:rules}:{enabled:joinOn?'1':'0',channel_url:channel});show(s('Settings saved.','تنظیمات ذخیره شد.'),true);}
  catch(e){if((e as Error).message==='AUTH_REQUIRED')setAuthRequired(true);show(failure(e),false);}finally{setBusy('');}
 }
 return <>
 <section className="card settings-card access-rule" data-no-i18n="true">
  <div className="settings-card-head"><ShieldCheck size={20}/><div><h2>{s('Rules and acceptance','قوانین و پذیرش کاربر')}</h2><p className="muted">{s('Set the service rules and require acceptance before entry.','قوانین سرویس و الزام پذیرش آن پیش از ورود را تنظیم کنید.')}</p></div></div>
  <MiniAppCheck checked={rulesOn} onChange={setRulesOn}>{s('Require users to accept the rules','دریافت تأیید قوانین از کاربران')}</MiniAppCheck>
  <label className="form-field"><span>{s('Rules text','متن قوانین')}</span><textarea dir="auto" rows={5} value={rules} placeholder={s('Enter your service rules','متن قوانین سرویس را وارد کنید')} onChange={e=>setRules(e.target.value)}/></label>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy} onClick={()=>void save('rules')}><Save size={16}/>{busy==='rules'?s('Saving…','در حال ذخیره…'):s('Save rules','ذخیره قوانین')}</button></div>
 </section>
 <section className="card settings-card access-rule" data-no-i18n="true">
  <div className="settings-card-head"><Users size={20}/><div><h2>{s('Required channel membership','عضویت اجباری در کانال')}</h2><p className="muted">{s('Ask users to join your channel before using the bot.','پیش از استفاده از ربات، عضویت کاربران در کانال را بررسی کنید.')}</p></div></div>
  <MiniAppCheck checked={joinOn} onChange={setJoinOn}>{s('Require channel membership','فعال‌کردن عضویت اجباری')}</MiniAppCheck>
  <label className="form-field"><span>{s('Channel username or URL','نام کاربری یا لینک کانال')}</span><input dir="ltr" value={channel} onChange={e=>setChannel(e.target.value)} placeholder="@channel / https://t.me/channel"/></label>
  <p className="settings-help">{s('The bot must be an administrator in this channel to verify membership.','برای بررسی عضویت، ربات باید در این کانال مدیر باشد.')}</p>
  <div className="settings-actions"><button className="btn primary" disabled={!!busy} onClick={()=>void save('force-join')}><Save size={16}/>{busy==='force-join'?s('Saving…','در حال ذخیره…'):s('Save channel','ذخیره کانال')}</button></div>
 </section></>;
}

