'use client';

import { useEffect, useState } from 'react';
import AnimatedLogin from '@/components/animated-login';

type LoginNotice = { kind: 'error' | 'info'; text: string } | null;

function safeNextUrl(value: string | null): string {
  const raw = (value || '/admin').trim();
  if (!raw.startsWith('/') || raw.startsWith('//') || raw.includes('://') || raw.startsWith('/login')) return '/admin';
  return raw;
}

export default function LoginPage() {
  const [nextUrl, setNextUrl] = useState('/admin');
  const [notice, setNotice] = useState<LoginNotice>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setNextUrl(safeNextUrl(params.get('next')));

    if (params.get('error')) setNotice({ kind: 'error', text: 'Incorrect username or password.' });
    else if (params.get('timeout')) setNotice({ kind: 'info', text: 'Your session has expired. Please sign in again.' });
    else if (params.get('updated')) setNotice({ kind: 'info', text: 'Login credentials were updated. Sign in with the new credentials.' });
  }, []);

  return <AnimatedLogin nextUrl={nextUrl} notice={notice} />;
}
