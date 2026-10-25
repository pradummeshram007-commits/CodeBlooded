/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        "cream": "#F5F1E6",
        "ivory": "#FCFAF3",
        "primary": "#66734A",
        "primary-dark": "#303B28",
        "sage": "#A4B18A",
        "accent-gold": "#B79A59",
        "dark-olive": "#252B20",
        "secondary-olive": "#727665",
        "border-subtle": "#DCDCCB",
        "border-olive": "#A4B18A",
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      boxShadow: {
        'olive-glow': '0 0 28px -4px rgba(102, 115, 74, 0.28), 0 0 10px rgba(183, 154, 89, 0.15)',
        'gold-glow': '0 0 26px -4px rgba(183, 154, 89, 0.3)',
      },
      keyframes: {
        marquee: {
          '0%': { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.95)', opacity: '0.8' },
          '50%': { transform: 'scale(1.08)', opacity: '0.3' },
          '100%': { transform: 'scale(0.95)', opacity: '0.8' },
        },
        'dash-flow': {
          to: { strokeDashoffset: '-40' },
        },
        'wobble-slow-1': {
          '0%, 100%': { transform: 'rotate(0deg) translate(0px, 0px)' },
          '25%': { transform: 'rotate(-2.5deg) translate(-1px, 1px)' },
          '50%': { transform: 'rotate(2deg) translate(1px, -1px)' },
          '75%': { transform: 'rotate(-1deg) translate(-0.5px, 0.5px)' },
        },
        'wobble-slow-2': {
          '0%, 100%': { transform: 'rotate(0deg) translate(0px, 0px)' },
          '25%': { transform: 'rotate(2deg) translate(1px, -1px)' },
          '50%': { transform: 'rotate(-1.5deg) translate(-1px, 0.5px)' },
          '75%': { transform: 'rotate(1deg) translate(0.5px, -0.5px)' },
        },
        'wobble-slow-3': {
          '0%, 100%': { transform: 'rotate(0deg) translate(0px, 0px)' },
          '33%': { transform: 'rotate(-2deg) translate(0.5px, -1px)' },
          '66%': { transform: 'rotate(1.5deg) translate(-0.5px, 1px)' },
        },
        'fade-slide-up': {
          '0%': { opacity: '0', transform: 'translateY(18px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        marquee: 'marquee 28s linear infinite',
        'pulse-ring': 'pulse-ring 4s ease-in-out infinite',
        'dash-flow': 'dash-flow 2s linear infinite',
        'wobble-1': 'wobble-slow-1 6s ease-in-out infinite',
        'wobble-2': 'wobble-slow-2 7.5s ease-in-out infinite',
        'wobble-3': 'wobble-slow-3 5.5s ease-in-out infinite',
        'fade-slide-up': 'fade-slide-up 0.7s cubic-bezier(0.16, 1, 0.3, 1) forwards',
      },
    },
  },
  plugins: [],
};
