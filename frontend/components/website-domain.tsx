'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, Globe, ShieldCheck } from 'lucide-react';
import { fetchJson, submitForm } from '@/lib/api';
import { useSettingsLanguage } from '@/lib/settings-language';

const statusUrl = '/admin/api/v2/settings/ssl';
type DomainStatus = { host_ready: boolean; job: { id?: string; state: string; domain?: string; reason?: string; login_url?: string } };

export function WebsiteDomain({ domain, setAuthRequired, onApplied }: { domain: string; setAuthRequired: (required: boolean) => void; onApplied: (loginUrl: string) => void }) {
  const { s } = useSettingsLanguage();
  const [target, setTarget] = useState(domain);
  const [status, setStatus] = useState<DomainStatus>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const waiting = ['queued', 'running'].includes(status?.job.state || '');

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function check() {
      try {
        const next = await fetchJson<DomainStatus>(statusUrl, controller.signal);
        if (!controller.signal.aborted) setStatus(next);
      } catch (cause) {
        if (!controller.signal.aborted && (cause as Error).message === 'AUTH_REQUIRED') setAuthRequired(true);
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(check, 3500);
      }
    }
    void check();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [setAuthRequired]);

  async function apply() {
    if (!target.trim() || busy || waiting) return;
    setBusy(true);
    setError('');
    try {
      await submitForm('/admin/settings/ssl/apply', { domain: target.trim() });
      setStatus(await fetchJson<DomainStatus>(statusUrl));
    } catch (cause) {
      const message = (cause as Error).message;
      if (message === 'AUTH_REQUIRED') setAuthRequired(true);
      else setError(message);
    } finally {
      setBusy(false);
    }
  }

  const reasons: Record<string, string> = {
    dns: s('The domain did not resolve for certificate validation. Check the DNS records.', 'دامنه برای صدور گواهی resolve نشد. رکوردهای DNS را بررسی کنید.'),
    port: s('Nginx could not serve the HTTP challenge on port 80. Check the port and other web servers.', 'Nginx نتوانست اعتبارسنجی HTTP را روی پورت ۸۰ انجام دهد. پورت و وب‌سرورهای دیگر را بررسی کنید.'),
    certificate: s("Let's Encrypt could not issue the certificate. Check DNS, port 80 and the Certbot log on the VPS.", 'صدور گواهی ناموفق بود. DNS، پورت ۸۰ و لاگ Certbot را روی VPS بررسی کنید.'),
    health: s('The new address could not serve a healthy D BOT panel.', 'پاسخ سالم پنل D BOT در آدرس جدید تأیید نشد.'),
    busy: s('A VPS domain change is already running. Try again when it finishes.', 'تغییر دامنه از VPS در حال اجراست. پس از پایان دوباره تلاش کنید.'),
    rollback: s('Website recovery could not be verified. Check the VPS journal.', 'بازیابی تنظیمات وب‌سایت تأیید نشد. لاگ VPS را بررسی کنید.'),
  };
  const job = status?.job;
  let newLogin = '';
  if (job?.state === 'completed' && job.login_url) {
    try {
      const url = new URL(job.login_url);
      if (['http:', 'https:'].includes(url.protocol)) newLogin = url.href;
    } catch { /* An invalid URL must never become a link. */ }
  }
  useEffect(() => { if (newLogin) onApplied(newLogin); }, [newLogin, onApplied]);

  return <section className="card settings-card">
    <div className="settings-card-head"><Globe size={20}/><div><h2>{s('Domain and HTTPS', 'دامنه و HTTPS')}</h2><p className="muted">{s('Enter the new domain, or apply HTTPS again for the current one.', 'دامنهٔ جدید را وارد کنید یا برای دامنهٔ فعلی HTTPS را دوباره اعمال کنید.')}</p></div></div>
    <form onSubmit={event => { event.preventDefault(); void apply(); }}>
      <label className="form-field"><span>{s('Domain name', 'نام دامنه')}</span><input required dir="ltr" value={target} placeholder="panel.example.com" disabled={busy || waiting} onChange={event => { setTarget(event.target.value); setError(''); }}/></label>
      <div className="settings-actions"><button type="submit" className="btn primary" disabled={busy || waiting || !target.trim() || status?.host_ready === false}><ShieldCheck size={17}/>{s('Request certificate and apply domain', 'درخواست گواهی و اعمال دامنه')}</button></div>
    </form>
    {status?.host_ready === false && <p className="muted">{s('The VPS worker is unavailable. Run', 'اجراکنندهٔ VPS در دسترس نیست. روی سرور اجرا کنید')} <code dir="ltr">sudo dbot update</code></p>}
    {(busy || waiting) && <p role="status">{s('The VPS is applying the domain and checking HTTPS.', 'VPS در حال اعمال دامنه و بررسی HTTPS است.')} {job?.domain && <bdi>{job.domain}</bdi>}</p>}
    {error && <p role="alert" className="settings-error">{error}</p>}
    {job?.state === 'failed' && <p role="alert" className="settings-error">{job.domain && <bdi>{job.domain} · </bdi>}{reasons[job.reason || ''] ?? s('The VPS could not apply this domain. Check the host journal.', 'اعمال دامنه روی VPS ناموفق بود. لاگ سرویس میزبان را بررسی کنید.')}</p>}
    {newLogin && <div className="settings-actions" role="status"><a className="btn" href={newLogin} target="_blank" rel="noopener noreferrer"><ExternalLink size={16}/>{s('Open the active panel', 'بازکردن پنل فعال')} <bdi>{job?.domain}</bdi></a></div>}
  </section>;
}
