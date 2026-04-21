import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'neon-buy': '#22d3ee',
        'neon-sell': '#ec4899',
        'radar-deep': '#0a0e14',
        'radar-surface': '#13112a',
        'glass-soft': 'rgba(255,255,255,0.08)',
        'glass-strong': 'rgba(255,255,255,0.15)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      backdropBlur: {
        glass: '20px',
      },
      boxShadow: {
        'glass-ambient': '0 4px 24px rgba(139,92,246,0.15)',
        'glass-elevated': '0 8px 32px rgba(139,92,246,0.25)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;
