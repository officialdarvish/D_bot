import type { Metadata, Viewport } from 'next';
import './globals.css';

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
      <body>{children}</body>
    </html>
  );
}
