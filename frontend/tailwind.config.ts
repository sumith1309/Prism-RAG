import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Geist",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["Geist Mono", "JetBrains Mono", "Menlo", "monospace"],
      },
      colors: {
        // Unified LIGHT premium palette — used by landing, sign-in, AND app.
        bg: {
          DEFAULT: "#fafafa",
          subtle: "#f5f5f7",
          elevated: "#ffffff",
        },
        surface: {
          DEFAULT: "#ffffff",
          hover: "#f5f5f7",
          active: "#eeeef1",
        },
        border: {
          DEFAULT: "#e5e5ea",
          strong: "#d2d2d7",
        },
        fg: {
          DEFAULT: "#1d1d1f",
          muted: "#52525b",
          subtle: "#8e8e93",
        },
        accent: {
          DEFAULT: "#5b47ff",
          hover: "#4a39d9",
          soft: "rgba(91, 71, 255, 0.08)",
        },
        clearance: {
          public: "#16a34a",
          internal: "#2563eb",
          confidential: "#d97706",
          restricted: "#dc2626",
        },
        // Legacy alias (a few components reference `light:*` for marketing pages).
        light: {
          bg: "#fafafa",
          surface: "#ffffff",
          elevated: "#fcfcfd",
          border: "#e5e5ea",
          borderStrong: "#d2d2d7",
          fg: "#1d1d1f",
          fgMuted: "#52525b",
          fgSubtle: "#8e8e93",
          accent: "#5b47ff",
          accentHover: "#4a39d9",
          accentSoft: "rgba(91, 71, 255, 0.08)",
        },
      },
      borderRadius: {
        sm: "6px",
        DEFAULT: "8px",
        md: "8px",
        lg: "12px",
        xl: "16px",
      },
      boxShadow: {
        // Premium light shadows — soft, deliberate, never harsh.
        subtle: "0 1px 2px rgba(17, 17, 26, 0.04), 0 0 0 1px rgba(17, 17, 26, 0.04)",
        card: "0 2px 8px rgba(17, 17, 26, 0.05), 0 0 0 1px rgba(17, 17, 26, 0.06)",
        pop: "0 24px 48px -12px rgba(17, 17, 26, 0.16), 0 0 0 1px rgba(17, 17, 26, 0.08)",
        "light-sm": "0 1px 2px rgba(17, 17, 26, 0.04), 0 0 0 1px rgba(17, 17, 26, 0.04)",
        "light-card": "0 2px 8px rgba(17, 17, 26, 0.05), 0 0 0 1px rgba(17, 17, 26, 0.06)",
        "light-pop": "0 24px 48px -12px rgba(17, 17, 26, 0.18), 0 0 0 1px rgba(17, 17, 26, 0.08)",
        "light-hang": "0 12px 28px -8px rgba(91, 71, 255, 0.35), 0 0 0 1px rgba(91, 71, 255, 0.18)",
        "accent-glow": "0 8px 24px -6px rgba(91, 71, 255, 0.22)",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-4px)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in": {
          "0%": { opacity: "0", transform: "translateX(-8px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "border-beam": {
          "100%": { "offset-distance": "100%" },
        },
      },
      animation: {
        float: "float 3.8s ease-in-out infinite",
        "fade-up": "fade-up 0.5s ease-out both",
        "slide-in": "slide-in 0.3s ease-out both",
        shimmer: "shimmer 2s linear infinite",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
