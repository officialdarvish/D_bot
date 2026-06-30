import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}', './lib/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'Vazirmatn', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Tahoma']
      },
      boxShadow: {
        glow: '0 24px 80px rgba(109, 40, 217, .28)',
        panel: '0 24px 90px rgba(0,0,0,.32)'
      },
      backgroundImage: {
        'cyber-grid': 'linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)'
      }
    }
  },
  plugins: []
};
export default config;
