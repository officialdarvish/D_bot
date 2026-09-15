'use client';

import { useMemo, useRef, useState, type FormEvent, type PointerEvent } from 'react';
import { ArrowLeft, Bot, Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react';

type LoginNotice = { kind: 'error' | 'info'; text: string } | null;

type AnimatedLoginProps = {
  nextUrl: string;
  notice?: LoginNotice;
  brand?: string;
  statusText?: string;
  title?: string;
  subtitle?: string;
};

const STAR_COUNT = 22;

function AnimatedBackdrop() {
  const stars = useMemo(
    () =>
      Array.from({ length: STAR_COUNT }, (_, i) => ({
        id: i,
        left: `${(i * 37 + 11) % 97}%`,
        top: `${(i * 53 + 7) % 92}%`,
        delay: `${((i * 0.37) % 4).toFixed(2)}s`,
        duration: `${(3.5 + ((i * 0.29) % 3)).toFixed(2)}s`,
        size: `${1 + (i % 3)}px`,
      })),
    [],
  );

  return (
    <div className="dbot-bg" aria-hidden="true">
      <div className="dbot-aurora dbot-aurora--a" />
      <div className="dbot-aurora dbot-aurora--b" />
      <div className="dbot-aurora dbot-aurora--c" />
      <div className="dbot-wave dbot-wave--1" />
      <div className="dbot-wave dbot-wave--2" />
      <div className="dbot-wave dbot-wave--3" />
      <div className="dbot-horizon" />
      {stars.map((star) => (
        <span
          className="dbot-star"
          key={star.id}
          style={{
            left: star.left,
            top: star.top,
            width: star.size,
            height: star.size,
            animationDelay: star.delay,
            animationDuration: star.duration,
          }}
        />
      ))}
    </div>
  );
}

export default function AnimatedLogin({
  nextUrl,
  notice = null,
  brand = 'D Bot Panel',
  statusText = 'Always by your side',
  title = 'Sign in to Admin Panel',
  subtitle = 'Professional bot management in a simple and secure workspace',
}: AnimatedLoginProps) {
  const pageRef = useRef<HTMLElement | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  const handlePointerMove = (event: PointerEvent<HTMLElement>) => {
    const node = pageRef.current;
    if (!node || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const x = event.clientX / window.innerWidth - 0.5;
    const y = event.clientY / window.innerHeight - 0.5;
    node.style.setProperty('--mx', `${x * 18}px`);
    node.style.setProperty('--my', `${y * 12}px`);
  };

  const handlePointerLeave = () => {
    const node = pageRef.current;
    if (!node) return;
    node.style.setProperty('--mx', '0px');
    node.style.setProperty('--my', '0px');
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    if (loading) {
      event.preventDefault();
      return;
    }
    setLoading(true);
  };

  return (
    <main
      ref={pageRef}
      className="dbot-login-page"
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      dir="ltr"
      lang="en"
    >
      <AnimatedBackdrop />

      <header className="dbot-topbar">
        <div className="dbot-brand" aria-label="D Bot Panel">
          <span className="dbot-brand-mark">D</span>
          <span>{brand}</span>
        </div>
        <div className="dbot-status">
          <span className="dbot-status-dot" />
          <span>{statusText}</span>
        </div>
      </header>

      <aside className="dbot-side-copy" aria-hidden="true">
        <strong>Smart management</strong>
        <span>More peace of mind</span>
        <i />
      </aside>

      <section className="dbot-login-card" aria-labelledby="dbot-login-title">
        <div className="dbot-card-shine" aria-hidden="true" />
        <div className="dbot-bot-icon" aria-hidden="true">
          <Bot size={49} strokeWidth={1.75} />
        </div>

        <h1 id="dbot-login-title">{title}</h1>
        <p className="dbot-subtitle">{subtitle}</p>

        {notice && (
          <div className={`dbot-message ${notice.kind === 'info' ? 'info' : ''}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
            {notice.text}
          </div>
        )}

        <form method="post" className="dbot-form" onSubmit={submit} autoComplete="on">
          <input type="hidden" name="next_url" value={nextUrl} />

          <label className="dbot-field">
            <UserRound className="dbot-field-icon" size={24} strokeWidth={1.7} aria-hidden="true" />
            <input
              type="text"
              name="username"
              autoComplete="username"
              placeholder="Username"
              aria-label="Username"
              maxLength={64}
              required
              autoFocus
              readOnly={loading}
            />
          </label>

          <label className="dbot-field">
            <LockKeyhole className="dbot-field-icon" size={23} strokeWidth={1.7} aria-hidden="true" />
            <input
              type={showPassword ? 'text' : 'password'}
              name="password"
              autoComplete="current-password"
              placeholder="Password"
              aria-label="Password"
              maxLength={256}
              required
              readOnly={loading}
            />
            <button
              type="button"
              className="dbot-eye"
              onClick={() => setShowPassword((value) => !value)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              disabled={loading}
            >
              {showPassword ? <Eye size={22} /> : <EyeOff size={22} />}
            </button>
          </label>

          <button className="dbot-submit" type="submit" disabled={loading}>
            <span>{loading ? 'Signing in...' : 'Sign in'}</span>
            <ArrowLeft size={26} strokeWidth={1.55} />
          </button>
        </form>

      </section>

      <footer className="dbot-footer">
        <span>Powered by Darvish Style</span>
        <span>Built to exceed expectations.</span>
      </footer>
    </main>
  );
}
