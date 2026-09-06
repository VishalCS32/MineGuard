/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces -- deliberately dark and single-mode. Deepened so saturated
        // marks read at full strength against them.
        plane: '#070c13',
        surface: '#121a24',
        'surface-2': '#18222e',
        'surface-3': '#222e3d',
        hairline: 'rgba(255,255,255,0.09)',

        // Ink
        ink: '#eaf1f8',
        'ink-2': '#9fb0c2',
        'ink-3': '#7286a0',

        // Brand
        brand: '#1fdd75',
        'brand-dim': '#12b45c',
        'brand-glow': 'rgba(31,221,117,0.18)',

        // Status palette -- fixed, never themed, never reused as a series colour.
        // Validated as an adjacent ramp on this surface: worst normal-vision
        // pair 17.9 and worst CVD pair 13.1 protan / 8.9 tritan, so the bands
        // separate on their own before the label and contour reinforce them.
        good: '#00c14f',
        warning: '#f2dc00',
        serious: '#ff7a00',
        critical: '#e80038',

        // Categorical series slots: maximum chroma at a lightness inside the
        // 0.48-0.67 band, validated against this surface.
        's1': '#258cff',
        's2': '#e96100',
        's3': '#00ab70',
        's4': '#9863ff',
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)',
        glow: '0 0 0 1px rgba(31,221,117,0.42), 0 0 26px -4px rgba(31,221,117,0.55)',
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
