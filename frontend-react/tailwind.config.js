/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0d1117",
        panel: "#161b22",
        "panel-alt": "#1c2230",
        border: "#30363d",
        accent: "#58a6ff",
        success: "#3fb950",
        danger: "#f85149",
        warning: "#d29922",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
