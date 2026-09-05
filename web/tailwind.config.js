/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces -- the dashboard is a deliberately dark, single-mode design.
        plane: '#0a0f16',
        surface: '#151c25',
        'surface-2': '#1b232e',
        'surface-3': '#222c38',
        hairline: 'rgba(255,255,255,0.08)',

        // Ink
        ink: '#e8eef5',
        'ink-2': '#9aa7b5',
        'ink-3': '#6b7889',

        // Brand
        brand: '#22c55e',
        'brand-dim': '#16a34a',
        'brand-glow': 'rgba(34,197,94,0.16)',

        // Status palette -- fixed, never themed, never reused as a series colour.
        good: '#0ca30c',
        warning: '#fab219',
        serious: '#ec835a',
        critical: '#d03b3b',

        // Categorical series slots, validated for this dark surface.
        's1': '#3987e5',
        's2': '#d95926',
        's3': '#199e70',
        's4': '#9085e9',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)',
        glow: '0 0 0 1px rgba(34,197,94,0.35), 0 0 24px -4px rgba(34,197,94,0.45)',
      },
      keyframes: {
        'pulse-ring': {
          '0%': { transform: 'scale(0.85)', opacity: '0.75' },
          '70%': { transform: 'scale(2.1)', opacity: '0' },
          '100%': { transform: 'scale(2.1)', opacity: '0' },
        },
        'dash-flow': { to: { strokeDashoffset: '-16' } },
        shimmer: { '100%': { transform: 'translateX(100%)' } },
      },
      animation: {
        'pulse-ring': 'pulse-ring 2.4s cubic-bezier(0.4,0,0.6,1) infinite',
        'dash-flow': 'dash-flow 1s linear infinite',
      },
    },
  },
  plugins: [],
};
