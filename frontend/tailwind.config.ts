import type { Config } from 'tailwindcss'

/** Tailwind v4 is CSS-first; live tokens live in src/index.css. */
const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        cobalt: '#2641E6',
        'cobalt-deep': '#1B33D6',
        ink: '#070B2E',
        paper: '#F3EFE6',
        'paper-muted': 'rgba(243,239,230,0.82)',
        'paper-label': 'rgba(243,239,230,0.90)',
        foam: '#C9F0E3',
        ember: '#FF5B2E',
        'ember-ink': '#B8320C',
        hairline: 'rgba(243,239,230,0.28)',
      },
      fontFamily: {
        display: ['Newsreader', 'Georgia', 'serif'],
        sans: ['Instrument Sans', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      borderRadius: { card: '2px', pill: '9999px' },
      transitionTimingFunction: { proteus: 'cubic-bezier(0.16, 1, 0.3, 1)' },
    },
  },
  plugins: [],
}

export default config
