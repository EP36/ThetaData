import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        panel: "var(--panel)",
        "panel-soft": "var(--panel-soft)",
        ink: "var(--ink)",
        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        danger: "var(--danger)"
      },
      boxShadow: {
        card: "0 12px 32px rgba(0, 0, 0, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
