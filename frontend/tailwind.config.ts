import type { Config } from 'tailwindcss'

/**
 * Proteus design system — tailwind.config.ts
 *
 * Tailwind v4 is CSS-first: the live token values live in `src/index.css` under
 * `@theme`. This file is loaded through the `@config` directive so that the
 * theme remains introspectable/tooling-friendly and mirrors the CSS tokens
 * one-for-one. Keep the two in sync.
 */
const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Core Proteus palette
        ink: '#0C0A09', // page background — near-black warm stone
        surface: '#1C1917', // cards, user bubbles
        elevated: '#292524', // raised surfaces, popovers, inputs
        accent: {
          DEFAULT: '#D4F268', // electric lime — the single accent
          dim: '#B7D64F',
          soft: '#E6F9A8',
        },
        fg: {
          DEFAULT: '#E7E5E4', // primary foreground
          muted: '#A8A29E', // secondary text
          faint: '#78716C', // tertiary / labels
        },
        hairline: 'rgba(255,255,255,0.1)', // borders & dividers
      },
      fontFamily: {
        display: ['Newsreader', 'ui-serif', 'Georgia', 'serif'],
        sans: ['"Instrument Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'SF Mono', 'Menlo', 'monospace'],
      },
      borderRadius: {
        card: '24px',
        pill: '9999px',
      },
      transitionTimingFunction: {
        proteus: 'cubic-bezier(0.32, 0.72, 0, 1)',
      },
      transitionDuration: {
        proteus: '300ms',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'drift': {
          '0%, 100%': { transform: 'translate3d(0,0,0) rotate(0deg)' },
          '50%': { transform: 'translate3d(0,-10px,0) rotate(-1.5deg)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '70%': { transform: 'scale(1.6)', opacity: '0' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.5s cubic-bezier(0.32, 0.72, 0, 1) both',
        'fade-in': 'fade-in 0.4s ease-out both',
        'drift': 'drift 7s ease-in-out infinite',
        'pulse-ring': 'pulse-ring 2.4s cubic-bezier(0.32, 0.72, 0, 1) infinite',
        'shimmer': 'shimmer 2.4s linear infinite',
      },
    },
  },
  plugins: [],
}

export default config
