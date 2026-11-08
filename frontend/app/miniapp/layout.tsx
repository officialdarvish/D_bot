import Script from 'next/script';
import type { Metadata } from 'next';
export const metadata: Metadata = { title: 'D Bot | مینی‌اپ تلگرام', description: 'خرید و مدیریت اشتراک‌های D Bot در تلگرام' };
export default function Layout({ children }: { children: React.ReactNode }) {
  return <><Script src="https://telegram.org/js/telegram-web-app.js" strategy="beforeInteractive" />{children}</>;
}
