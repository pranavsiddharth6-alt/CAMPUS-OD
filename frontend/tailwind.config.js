/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: '#0B2545',    // Primary institutional navy
          secondary: '#133E87',  // Secondary accent navy
          surface: '#F8FAFC',    // Slate tint for backgrounds
          border: '#E2E8F0',     // Subtle slate borders
          muted: '#64748B',      // Secondary text
          dark: '#0F172A',       // High contrast body text
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
