import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'D BOT Admin',
  description: 'Modern D BOT administration dashboard'
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
