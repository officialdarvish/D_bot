import type { Metadata, Viewport } from 'next';
import './globals.css';
import { UiLanguageProvider } from '@/lib/ui-language';

export const metadata: Metadata = {
  title: 'D Bot Panel',
  description: 'D Bot administration dashboard',
};

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#07111f',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://cdn.jsdelivr.net" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css"
        />
      </head>
      <body><UiLanguageProvider>{children}</UiLanguageProvider></body>
    </html>
  );
}
