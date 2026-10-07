'use client';

import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  BadgeCheck,
  Bot,
  CircleDot,
  Eye,
  FilePenLine,
  Layers3,
  MessageSquareText,
  MousePointerClick,
  RotateCcw,
  Save,
  Search,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import { fetchJson, submitForm } from '@/lib/api';
import { useUiLanguage } from '@/lib/ui-language';

type CustomTextItem = {
  key: string;
  default: string;
  current: string;
  category: string;
  section: string;
  kind: 'message' | 'button' | string;
  source: string;
  line: number;
  symbol?: string;
  placeholders?: string[];
  customized: boolean;
  enabled?: boolean | null;
  legacy_key?: string | null;
};

type CustomTextsApi = {
  ok: boolean;
  items: CustomTextItem[];
  total: number;
  modified: number;
  categories: string[];
  sections: string[];
};

type StatusFilter = 'all' | 'custom' | 'default';

const INITIAL_VISIBLE = 60;
const VISIBLE_STEP = 60;

const CATEGORY_LABELS: Record<string, string> = {
  'منو و دکمه‌های اصلی': 'Main Menu & Buttons',
  'شروع و صفحه اصلی': 'Start & Home',
  'خرید و پرداخت': 'Purchase & Payment',
  'کانفیگ‌های من': 'My Configs',
  'حساب کاربری و کیف پول': 'Account & Wallet',
  'پشتیبانی و تیکت': 'Support & Tickets',
  'نمایندگی': 'Reseller',
  'اکانت تست': 'Test Account',
  'پیام خصوصی': 'Private Messages',
  'تحویل سرویس': 'Service Delivery',
  'پروفایل و آموزش اتصال': 'Profile & Connection Guide',
  'تمدید سرویس': 'Service Renewal',
  'پیام‌های عمومی کاربر': 'General User Messages',
  'هشدارهای سرویس': 'Service Alerts',
  'انقضا و حذف سرویس': 'Expiration & Removal',
  'دعوت و پورسانت': 'Referral & Commission',
  'تعامل کاربر': 'User Interaction',
  'سایر پیام‌های کاربر': 'Other User Messages',
};

const SECTION_LABELS: Record<string, string> = {
  'پرداخت، رسید و تأیید خرید': 'Payment, Receipt & Approval',
  'ساخت و تحویل سرویس': 'Service Creation & Delivery',
  'اطلاعات کانفیگ': 'Config Information',
  'انتخاب سرویس و پلن': 'Service & Plan Selection',
  'فرآیند خرید': 'Purchase Flow',
  'تمدید سرویس': 'Service Renewal',
  'مدیریت دستگاه و HWID': 'Device & HWID Management',
  'حذف کانفیگ': 'Config Removal',
  'مدیریت کانفیگ': 'Config Management',
  'مشاهده کانفیگ‌ها': 'View Configs',
  'کیف پول و رسید پرداخت': 'Wallet & Payment Receipt',
  'حساب کاربری': 'User Account',
  'ثبت و پیگیری تیکت': 'Create & Track Tickets',
  'رسید و شارژ نمایندگی': 'Reseller Receipt & Balance',
  'مدیریت یوزر نمایندگی': 'Reseller User Management',
  'پنل نمایندگی': 'Reseller Panel',
  'ساخت اکانت تست': 'Create Test Account',
  'گفتگوی خصوصی با مدیریت': 'Private Chat with Admin',
  'کارت و مشخصات سرویس': 'Service Card & Details',
  'پروفایل OpenVPN': 'OpenVPN Profile',
  'پیام نتیجه تمدید': 'Renewal Result Message',
  'ورود، قوانین و منوی اصلی': 'Entry, Rules & Main Menu',
  'دکمه‌های قابل مشاهده کاربر': 'User-visible Buttons',
  'هشدار حجم، زمان و غیرفعال شدن': 'Usage, Time & Disable Alerts',
  'اعلان انقضا و حذف': 'Expiration & Removal Notice',
  'دعوت، جایزه و پورسانت': 'Referral, Reward & Commission',
  'خطا و راهنمای ورودی': 'Input Errors & Guidance',
  'تعامل کاربر': 'User Interaction',
};

const categoryLabel = (value: string) => CATEGORY_LABELS[value] || value;
const sectionLabel = (value: string) => SECTION_LABELS[value] || value;

export function CustomSection({
  reloadKey,
  setAuthRequired,
  show,
}: {
  reloadKey: number;
  setAuthRequired: (value: boolean) => void;
  show: (message: string, good?: boolean) => void;
}) {
  const [data, setData] = useState<CustomTextsApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);
  const [category, setCategory] = useState('all');
  const [section, setSection] = useState('all');
  const [kind, setKind] = useState('all');
  const [status, setStatus] = useState<StatusFilter>('all');
  const [selectedKey, setSelectedKey] = useState('');
  const [draft, setDraft] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const { language, t } = useUiLanguage();
  const formatNumber = (value: number) => value.toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US');
  const uiCategoryLabel = (value: string) => t(categoryLabel(value));
  const uiSectionLabel = (value: string) => t(sectionLabel(value));

  async function load() {
    setLoading(true);
    setError('');
    try {
      const json = await fetchJson<CustomTextsApi>('/api/admin/custom-texts');
      setData(json);
      const nextKey = selectedKey && json.items.some((x) => x.key === selectedKey)
        ? selectedKey
        : (json.items[0]?.key || '');
      setSelectedKey(nextKey);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [reloadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const q = deferredQuery.trim().toLowerCase();
    return (data?.items || []).filter((item) => {
      if (category !== 'all' && item.category !== category) return false;
      if (section !== 'all' && item.section !== section) return false;
      if (kind !== 'all' && item.kind !== kind) return false;
      if (status === 'custom' && !item.customized) return false;
      if (status === 'default' && item.customized) return false;
      if (!q) return true;
      return [item.default, item.current, item.category, categoryLabel(item.category), uiCategoryLabel(item.category), item.section, sectionLabel(item.section), uiSectionLabel(item.section), item.symbol || '']
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [data, deferredQuery, category, section, kind, status, language]);

  const visibleItems = useMemo(
    () => filtered.slice(0, visibleCount),
    [filtered, visibleCount]
  );

  const selected = useMemo(
    () => filtered.find((item) => item.key === selectedKey) || filtered[0] || null,
    [filtered, selectedKey]
  );


  const categoryOptions = useMemo(
    () => [...(data?.categories || [])].sort((a, b) => uiCategoryLabel(a).localeCompare(uiCategoryLabel(b), language === 'fa' ? 'fa' : 'en')),
    [data, language]
  );

  const sectionOptions = useMemo(
    () => [...(data?.sections || [])].sort((a, b) => uiSectionLabel(a).localeCompare(uiSectionLabel(b), language === 'fa' ? 'fa' : 'en')),
    [data, language]
  );

  useEffect(() => {
    setVisibleCount(INITIAL_VISIBLE);
  }, [deferredQuery, category, section, kind, status]);

  useEffect(() => {
    if (!selected) return;
    setDraft(selected.current);
    setEnabled(selected.enabled !== false);
    if (selected.key !== selectedKey) setSelectedKey(selected.key);
  }, [selected?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveSelected() {
    if (!selected) return;
    if (selected.kind === 'button' && draft.length > 64) {
      show(t('Telegram button text cannot exceed 64 characters.'), false);
      return;
    }
    if (selected.kind !== 'button' && draft.length > 4096) {
      show(t('Telegram message text cannot exceed 4096 characters.'), false);
      return;
    }
    setSaving(true);
    try {
      await submitForm('/api/admin/custom-texts', {
        key: selected.key,
        value: draft,
        ...(selected.enabled !== null && selected.enabled !== undefined ? { enabled: enabled ? '1' : '0' } : {}),
      });
      show(t('Text saved successfully.'), true);
      await load();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      show(message === 'AUTH_REQUIRED' ? t('Please sign in to the panel again.') : message, false);
    } finally {
      setSaving(false);
    }
  }

  async function resetSelected() {
    if (!selected || !window.confirm(t('Reset this text to the project default?'))) return;
    try {
      await submitForm('/api/admin/custom-texts/reset', { key: selected.key });
      show(t('Text reset to the default value.'), true);
      await load();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      show(message, false);
    }
  }

  async function resetAll() {
    if (!window.confirm(t('Reset all customized messages and buttons to their defaults?'))) return;
    try {
      await submitForm('/api/admin/custom-texts/reset', { reset_all: '1' });
      show(t('All Custom texts were reset to their defaults.'), true);
      await load();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      show(message, false);
    }
  }

  if (loading && !data) {
    return (
      <div className="custom-loading panel" data-no-i18n="true">
        <div className="custom-loading-orb"><Sparkles size={20} /></div>
        <div><strong>{t('Preparing Custom Center…')}</strong><div className="muted">{t('Loading user-visible bot messages and buttons.')}</div></div>
      </div>
    );
  }
  if (error && !data) return <div className="panel" data-no-i18n="true"><div style={{ color: 'var(--red)' }}>{error}</div></div>;

  const total = data?.total || 0;
  const modified = data?.modified || 0;
  const defaultCount = Math.max(total - modified, 0);
  const maxLength = selected?.kind === 'button' ? 64 : 4096;
  const draftRatio = Math.min((draft.length / maxLength) * 100, 100);

  return (
    <div className="custom-center" data-no-i18n="true">
      <section className="custom-hero">
        <div className="custom-hero-copy">
          <div className="custom-hero-icon"><SlidersHorizontal size={22} /></div>
          <div>
            <div className="custom-eyebrow"><Sparkles size={14} /> {t('D Bot Custom Center')}</div>
            <h2>{t('Shape every user-facing message around your brand')}</h2>
            <p>{t('Only real user journeys are shown here — from start and purchase to payment, receipt approval, service delivery, renewal, support, and service alerts.')}</p>
          </div>
        </div>
        <button className="btn danger custom-reset-all" onClick={resetAll}>
          <RotateCcw size={16} /> {t('Reset All')}
        </button>
      </section>

      <section className="custom-stats" aria-label={t('Custom text statistics')}>
        <div className="custom-stat-card custom-stat-purple">
          <span className="custom-stat-icon"><MessageSquareText size={19} /></span>
          <div><small>{t('Total User Texts')}</small><strong>{formatNumber(total)}</strong></div>
        </div>
        <div className="custom-stat-card custom-stat-green">
          <span className="custom-stat-icon"><BadgeCheck size={19} /></span>
          <div><small>{t('Customized')}</small><strong>{formatNumber(modified)}</strong></div>
        </div>
        <div className="custom-stat-card custom-stat-blue">
          <span className="custom-stat-icon"><CircleDot size={19} /></span>
          <div><small>{t('Default')}</small><strong>{formatNumber(defaultCount)}</strong></div>
        </div>
        <div className="custom-stat-card custom-stat-cyan">
          <span className="custom-stat-icon"><Layers3 size={19} /></span>
          <div><small>{t('Categories')}</small><strong>{formatNumber(data?.categories?.length || 0)}</strong></div>
        </div>
      </section>

      <section className="custom-toolbar panel">
        <label className="custom-search">
          <Search size={17} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('Search user-facing bot messages…')} />
          {query && <button type="button" className="custom-search-clear" onClick={() => setQuery('')} aria-label={t('Clear search')}>×</button>}
        </label>

        <div className="custom-segment" aria-label={t('Text type')}>
          <button className={kind === 'all' ? 'active' : ''} onClick={() => setKind('all')}>{t('All')}</button>
          <button className={kind === 'message' ? 'active' : ''} onClick={() => setKind('message')}><MessageSquareText size={14} /> {t('Message')}</button>
          <button className={kind === 'button' ? 'active' : ''} onClick={() => setKind('button')}><MousePointerClick size={14} /> {t('Button')}</button>
        </div>

        <select className="custom-select" value={category} onChange={(e) => setCategory(e.target.value)} aria-label={t('Category')}>
          <option value="all">{t('All Categories')}</option>
          {categoryOptions.map((value) => <option key={value} value={value}>{uiCategoryLabel(value)}</option>)}
        </select>

        <select className="custom-select" value={section} onChange={(e) => setSection(e.target.value)} aria-label={t('User stage')}>
          <option value="all">{t('All User Stages')}</option>
          {sectionOptions.map((value) => <option key={value} value={value}>{uiSectionLabel(value)}</option>)}
        </select>

        <select className="custom-select compact" value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} aria-label={t('Text status')}>
          <option value="all">{t('All Statuses')}</option>
          <option value="custom">{t('Customized Only')}</option>
          <option value="default">{t('Default Only')}</option>
        </select>
      </section>

      <div className="custom-result-line">
        <span><strong>{formatNumber(filtered.length)}</strong> {t('matching items')}</span>
        {loading && <span className="custom-syncing">{t('Syncing…')}</span>}
      </div>

      <section className="custom-workspace">
        <div className="custom-list-panel panel">
          <div className="custom-list-head">
            <div><strong>{t('Editable User Texts')}</strong><small>{t('Select an item to edit and preview it')}</small></div>
            <span className="badge">{formatNumber(visibleItems.length)} / {formatNumber(filtered.length)}</span>
          </div>

          <div className="custom-list" role="listbox" aria-label={t('Bot texts')}>
            {visibleItems.length === 0 ? (
              <div className="custom-empty">
                <Search size={28} />
                <strong>{t('No matching text found')}</strong>
                <span>{t('Try changing the search term or filters.')}</span>
              </div>
            ) : visibleItems.map((item) => {
              const isActive = item.key === selected?.key;
              return (
                <button
                  key={item.key}
                  className={`custom-text-card${isActive ? ' active' : ''}${item.customized ? ' customized' : ''}`}
                  onClick={() => setSelectedKey(item.key)}
                  role="option"
                  aria-selected={isActive}
                >
                  <span className={`custom-kind-icon ${item.kind === 'button' ? 'button' : 'message'}`}>
                    {item.kind === 'button' ? <MousePointerClick size={16} /> : <MessageSquareText size={16} />}
                  </span>
                  <span className="custom-card-content">
                    <span className="custom-card-meta">
                      <b>{item.kind === 'button' ? t('Button') : t('Message')}</b>
                      <span className="custom-tag-row">
                        <em className="custom-category-tag">{uiCategoryLabel(item.category)}</em>
                        {item.section && <em className="custom-section-tag">{uiSectionLabel(item.section)}</em>}
                      </span>
                    </span>
                    <span className="custom-card-text" dir="auto" data-no-i18n="true">{item.current}</span>
                    <span className="custom-card-status">
                      <i className={item.customized ? 'on' : ''} />
                      {item.customized ? t('Customized') : t('Default')}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          {visibleCount < filtered.length && (
            <button className="custom-load-more" onClick={() => setVisibleCount((value) => value + VISIBLE_STEP)}>
              {t(`Show ${formatNumber(Math.min(VISIBLE_STEP, filtered.length - visibleCount))} more`)}
            </button>
          )}
        </div>

        <div className="custom-editor-panel panel">
          {!selected ? (
            <div className="custom-editor-empty"><FilePenLine size={34} /><strong>{t('Select a text')}</strong><span>{t('The editor and live preview will appear here.')}</span></div>
          ) : (
            <>
              <div className="custom-editor-head">
                <div className="custom-editor-title">
                  <span className={`custom-kind-icon ${selected.kind === 'button' ? 'button' : 'message'}`}>
                    {selected.kind === 'button' ? <MousePointerClick size={17} /> : <MessageSquareText size={17} />}
                  </span>
                  <div>
                    <strong>{selected.kind === 'button' ? t('Edit Button Text') : t('Edit Bot Message')}</strong>
                    <span className="custom-editor-tags">
                      <em className="custom-category-tag">{uiCategoryLabel(selected.category)}</em>
                      {selected.section && <em className="custom-section-tag">{uiSectionLabel(selected.section)}</em>}
                    </span>
                  </div>
                </div>
                <span className={selected.customized ? 'badge green' : 'badge'}>{selected.customized ? t('Customized') : t('Project Default')}</span>
              </div>

              <div className="custom-preview-card">
                <div className="custom-preview-head"><Eye size={15} /> {t('Live Preview')}</div>
                <div className="telegram-preview">
                  <div className="telegram-avatar"><Bot size={18} /></div>
                  <div className="telegram-bubble" dir="auto" data-no-i18n="true">
                    {draft || <span className="muted">{t('This text is empty…')}</span>}
                  </div>
                </div>
                {selected.kind === 'button' && <div className="telegram-button-preview" dir="auto" data-no-i18n="true">{draft || t('Button label')}</div>}
              </div>

              {selected.placeholders && selected.placeholders.length > 0 && (
                <div className="custom-placeholders">
                  <div><Sparkles size={14} /><strong>{t('Dynamic Placeholders')}</strong><span>{t('Keep these tokens so runtime values continue to work.')}</span></div>
                  <div className="custom-placeholder-list">
                    {selected.placeholders.map((p) => <code key={p}>{`{${p}}`}</code>)}
                  </div>
                </div>
              )}

              <label className="custom-textarea-wrap">
                <span>{t('Editable Text')}</span>
                <textarea
                  dir="auto"
                  data-no-i18n="true"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={selected.kind === 'button' ? 3 : 9}
                  maxLength={maxLength + 200}
                />
                <div className="custom-char-row">
                  <span>{selected.kind === 'button' ? t('Maximum 64 characters for a Telegram button') : t('Maximum 4096 characters for a Telegram message')}</span>
                  <b className={draft.length > maxLength ? 'danger' : ''}>{formatNumber(draft.length)} / {formatNumber(maxLength)}</b>
                </div>
                <div className="custom-char-track"><i className={draft.length > maxLength ? 'danger' : ''} style={{ width: `${draftRatio}%` }} /></div>
              </label>

              {selected.enabled !== null && selected.enabled !== undefined && (
                <label className={`custom-toggle-card${enabled ? ' enabled' : ''}`}>
                  <span><strong>{t('Show this button in the user menu')}</strong><small>{t('Turn this off to hide the button from users.')}</small></span>
                  <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
                  <i className="custom-toggle" aria-hidden="true" />
                </label>
              )}

              <details className="custom-default-details">
                <summary>{t('View Project Default')}</summary>
                <pre dir="auto" data-no-i18n="true">{selected.default}</pre>
              </details>

              <details className="custom-default-details technical">
                <summary>{t('Technical Details')}</summary>
                <div className="custom-technical-grid" dir="ltr">
                  <span><b>{t('Source')}</b>{selected.source}:{selected.line}</span>
                  {selected.symbol && <span><b>{t('Symbol')}</b>{selected.symbol}</span>}
                </div>
              </details>

              <div className="custom-editor-actions">
                <button className="btn primary" onClick={saveSelected} disabled={saving || draft.length > maxLength}>
                  <Save size={16} /> {saving ? t('Saving…') : t('Save Changes')}
                </button>
                <button className="btn" onClick={resetSelected}><RotateCcw size={16} /> {t('Reset to Default')}</button>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
