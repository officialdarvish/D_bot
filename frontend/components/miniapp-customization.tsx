'use client';

import { useEffect, useId, useMemo, useState } from 'react';
import { Eye, MessageSquareText, Pencil, RotateCcw, Save, Search, Settings2, X } from 'lucide-react';
import { AdminDialog } from '@/components/admin-dialog';
import { MiniAppSettings, type MiniAppSettingsProps } from '@/components/miniapp-settings';
import { fetchJson, submitForm } from '@/lib/api';
import { miniAppCopyCatalog, type CopyKey, type CopyOverrides } from '@/lib/miniapp-copy';
import { useSettingsLanguage } from '@/lib/settings-language';

const groups = [
  ['home', 'Home, navigation & services', 'خانه، منو و سرویس‌ها'],
  ['steps', 'Purchase steps', 'مراحل خرید'],
  ['checkout', 'Checkout & orders', 'خرید و پیگیری سفارش'],
  ['payment', 'Payment card', 'کارت پرداخت'],
  ['actions', 'Renewals, balances & service actions', 'تمدید، شارژ و مدیریت سرویس'],
  ['conversion', 'Plan conversion', 'تبدیل تعرفه'],
  ['trial', 'Trial account', 'اکانت تست'],
  ['ownership', 'Ownership transfer', 'انتقال مالکیت'],
  ['reseller', 'Reseller registration', 'ثبت‌نام نمایندگی'],
  ['panels', 'Panel service creation', 'ساخت کانفیگ پنل'],
  ['wallet', 'Reseller wallet', 'کیف پول نماینده'],
  ['profiles', 'Connection profiles', 'پروفایل‌های اتصال'],
  ['help', 'Rules & tutorials', 'قوانین و آموزش'],
] as const;
const fields = Object.entries(miniAppCopyCatalog).map(([id, field]) => ({ id: id as CopyKey, ...field }));
const pageSize = 24;
const endpoint = '/admin/api/v2/miniapp/texts';
const variablesIn = (text: string) => Array.from(new Set(text.match(/\{[A-Za-z][A-Za-z0-9_]*\}/g) || [])).sort();
const includesAllVariables = (original: string, edited: string) =>
  JSON.stringify(variablesIn(original)) === JSON.stringify(variablesIn(edited));

type CopyEditorProps = MiniAppSettingsProps & { openSharedSection?: (section: 'rules' | 'tutorials') => void };

function MiniAppCopyEditor({ reloadKey, setAuthRequired, show, onDirtyChange, openSharedSection }: CopyEditorProps) {
  const { s, language, failure } = useSettingsLanguage();
  const [overrides, setOverrides] = useState<CopyOverrides | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [request, setRequest] = useState(0);
  const [group, setGroup] = useState('all');
  const [kind, setKind] = useState('all');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(pageSize);
  const [selected, setSelected] = useState<typeof fields[number] | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const inputId = useId();

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    fetchJson<{ overrides: CopyOverrides }>(endpoint, controller.signal).then(result => {
      if (!controller.signal.aborted) setOverrides(result.overrides);
    }).catch((cause: Error) => {
      if (controller.signal.aborted) return;
      if (cause.message === 'AUTH_REQUIRED') setAuthRequired(true);
      setError(cause);
    });
    return () => controller.abort();
  }, [reloadKey, request, setAuthRequired]);

  const current = selected ? overrides?.[selected.id] ?? selected.text : '';
  const dirty = !!selected && draft !== current;
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);

  const filtered = useMemo(() => {
    const search = query.trim().toLowerCase();
    return fields.filter(field =>
      (group === 'all' || field.group === group) && (kind === 'all' || field.kind === kind) &&
      (!search || `${field.text} ${overrides?.[field.id] || ''}`.toLowerCase().includes(search))
    );
  }, [group, kind, overrides, query]);

  const fieldGroup = (id: string) => {
    const label = groups.find(([key]) => key === id);
    return label ? s(label[1], label[2]) : '';
  };
  const fieldKind = (value: string) => value === 'button' ? s('Button', 'دکمه') : s('Text', 'متن');
  function close() {
    if (busy || (dirty && !window.confirm(s('Discard unsaved changes?', 'تغییرات ذخیره‌نشده کنار گذاشته شوند؟')))) return;
    setSelected(null);
  }

  async function save(reset = false) {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const id = selected.id;
      const result: { changes: CopyOverrides } = await submitForm(endpoint, {
        texts_json: JSON.stringify({ [id]: reset ? '' : draft }),
      });
      setOverrides(previous => {
        const next = { ...previous };
        const value = result.changes[id];
        if (value) next[id] = value;
        else delete next[id];
        return next;
      });
      setSelected(null);
      show(reset ? s('Default Mini App text restored.', 'متن پیش‌فرض مینی‌اپ برگشت.') : s('Mini App text saved.', 'متن مینی‌اپ ذخیره شد.'), true);
    } catch (cause) {
      if (cause instanceof Error && cause.message === 'AUTH_REQUIRED') setAuthRequired(true);
      show(failure(cause), false);
    } finally {
      setBusy(false);
    }
  }

  const maxLength = selected?.kind === 'button' ? 96 : 700;
  const valid = !!selected && Array.from(draft.trim()).length <= maxLength && !!draft.trim() && includesAllVariables(selected.text, draft);
  if (!overrides) return <section className="panel" data-no-i18n="true">
    <p role={error ? 'alert' : 'status'}>{error ? failure(error) : s('Loading Mini App texts…', 'در حال دریافت متن‌های مینی‌اپ…')}</p>
    {error && <button type="button" className="btn" onClick={() => setRequest(value => value + 1)}>{s('Retry', 'تلاش دوباره')}</button>}
  </section>;

  return <section className="panel cj-flow" data-no-i18n="true" dir={language === 'fa' ? 'rtl' : 'ltr'}>
    <header className="cj-section-head">
      <div><h2>{s('Mini App texts and buttons', 'متن‌ها و دکمه‌های مینی‌اپ')}</h2><p>{s('Find a label by screen or text. Saved edits appear the next time the Mini App loads its data.', 'با انتخاب صفحه یا جست‌وجو، متن دلخواه را پیدا کن. تغییرات پس از بارگیری دوبارهٔ اطلاعات مینی‌اپ نمایش داده می‌شوند.')}</p></div>
    </header>
    <div className="cj-miniapp-filters">
      <label className="form-field"><span>{s('Screen', 'صفحه')}</span><select value={group} onChange={event => { setGroup(event.target.value); setLimit(pageSize); }}>
        <option value="all">{s('All screens', 'همهٔ صفحه‌ها')}</option>
        {groups.map(([key, en, fa]) => <option key={key} value={key}>{s(en, fa)}</option>)}
      </select></label>
      <label className="form-field"><span>{s('Type', 'نوع')}</span><select value={kind} onChange={event => { setKind(event.target.value); setLimit(pageSize); }}>
        <option value="all">{s('All types', 'همهٔ نوع‌ها')}</option><option value="button">{s('Buttons', 'دکمه‌ها')}</option><option value="text">{s('Texts', 'متن‌ها')}</option>
      </select></label>
      <label className="form-field"><span>{s('Search texts', 'جست‌وجوی متن')}</span><span className="cj-search-field"><Search size={17}/><input type="search" dir="auto" value={query} onChange={event => { setQuery(event.target.value); setLimit(pageSize); }} /></span></label>
    </div>
    {openSharedSection && (group === 'help' || group === 'all') && <div className="cj-miniapp-tabs">
      <button type="button" className="btn" onClick={() => openSharedSection('rules')}>{s('Edit shared rules text', 'ویرایش متن مشترک قوانین')}</button>
      <button type="button" className="btn" onClick={() => openSharedSection('tutorials')}>{s('Edit shared tutorials and videos', 'ویرایش آموزش‌ها و ویدیوهای مشترک')}</button>
    </div>}
    <div className="cj-miniapp-results">
      {filtered.slice(0, limit).map(field => <button type="button" key={field.id} className={`cj-message ${overrides[field.id] ? 'is-custom' : ''}`} onClick={() => { setSelected(field); setDraft(overrides[field.id] ?? field.text); }}>
        <span className="cj-message-text" dir="auto">{overrides[field.id] ?? field.text}</span>
        <span className="cj-message-footer"><span>{fieldGroup(field.group)} · {fieldKind(field.kind)}</span><span><Pencil size={14}/>{overrides[field.id] ? s('Customized', 'سفارشی') : s('Edit', 'ویرایش')}</span></span>
      </button>)}
    </div>
    {!filtered.length && <p className="muted" role="status">{s('No text matches this search.', 'متنی مطابق جست‌وجو پیدا نشد.')}</p>}
    {filtered.length > limit && <button type="button" className="btn cj-more" onClick={() => setLimit(value => value + pageSize)}>{s('Show more', 'نمایش بیشتر')}</button>}
    {selected && <AdminDialog label={s('Edit Mini App text', 'ویرایش متن مینی‌اپ')} onClose={close} busy={busy}>
      <section className="modal-card cj-editor" data-no-i18n="true" dir={language === 'fa' ? 'rtl' : 'ltr'}>
        <header className="modal-head"><div><span className="cj-editor-section">{fieldGroup(selected.group)}</span><h2>{s('Edit Mini App text', 'ویرایش متن مینی‌اپ')}</h2></div><button type="button" className="icon-btn" aria-label={s('Close', 'بستن')} disabled={busy} onClick={close}><X size={19}/></button></header>
        <div className="cj-editor-grid">
          <form onSubmit={event => { event.preventDefault(); if (valid && dirty) void save(); }}>
            <label className="form-field cj-edit-field" htmlFor={inputId}><span>{s('Your text', 'متن شما')}</span><textarea id={inputId} rows={selected.kind === 'button' ? 2 : 5} value={draft} disabled={busy} onChange={event => setDraft(event.target.value)} dir="auto"/><small>{Array.from(draft.trim()).length} / {maxLength}</small></label>
            {!!variablesIn(selected.text).length && <p className="muted" dir="auto">{s('Keep these variables:', 'این متغیرها را حفظ کن:')} <code dir="ltr">{variablesIn(selected.text).join(' ')}</code></p>}
            <details className="cj-default"><summary>{s('See default text', 'دیدن متن پیش‌فرض')}</summary><pre dir="auto">{selected.text}</pre></details>
            <footer className="cj-editor-actions"><button type="submit" className="btn primary" disabled={!dirty || !valid || busy}><Save size={16}/>{busy ? s('Saving…', 'در حال ذخیره…') : s('Save text', 'ذخیرهٔ متن')}</button><button type="button" className="btn" disabled={!overrides[selected.id] || busy} onClick={() => void save(true)}><RotateCcw size={16}/>{s('Restore default', 'بازگشت به پیش‌فرض')}</button></footer>
          </form>
          <aside className="cj-preview-panel"><h3><Eye size={17}/>{s('Live preview', 'پیش‌نمایش زنده')}</h3><div className={`cj-live-preview ${selected.kind === 'button' ? 'cj-live-button' : ''}`} dir="auto">{draft.trim() ? draft : selected.text}</div></aside>
        </div>
      </section>
    </AdminDialog>}
  </section>;
}

export function MiniAppCustomization({ initialTab = 'copy', onDirtyChange, openSharedSection, ...props }: CopyEditorProps & { initialTab?: 'copy' | 'settings' }) {
  const { s, language } = useSettingsLanguage();
  const [tab, setTab] = useState(initialTab);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  function pick(next: typeof tab) {
    if (tab === next || (dirty && !window.confirm(s('Discard unsaved changes?', 'تغییرات ذخیره‌نشده کنار گذاشته شوند؟')))) return;
    setDirty(false);
    setTab(next);
  }
  return <div className="custom-journeys" data-no-i18n="true" dir={language === 'fa' ? 'rtl' : 'ltr'}>
    <nav className="cj-miniapp-tabs" aria-label={s('Mini App customization', 'سفارشی‌سازی مینی‌اپ')}>
      <button type="button" className={`btn ${tab === 'copy' ? 'primary' : ''}`} aria-pressed={tab === 'copy'} onClick={() => pick('copy')}><MessageSquareText size={17}/>{s('Texts and buttons', 'متن‌ها و دکمه‌ها')}</button>
      <button type="button" className={`btn ${tab === 'settings' ? 'primary' : ''}`} aria-pressed={tab === 'settings'} onClick={() => pick('settings')}><Settings2 size={17}/>{s('Settings and links', 'تنظیمات و لینک‌ها')}</button>
    </nav>
    {tab === 'copy' ? <MiniAppCopyEditor {...props} onDirtyChange={setDirty} openSharedSection={openSharedSection}/> : <MiniAppSettings {...props} onDirtyChange={setDirty}/>}
  </div>;
}
