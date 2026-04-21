import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Le build React est copié dans l'image Docker et servi par FastAPI
// (same-origin, cookies HttpOnly preservés). En dev local, on proxy
// /api et /ws vers le backend Python qui tourne sur localhost:8000.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    // Assets hashés par Vite → cache long + busting automatique.
    assetsDir: "assets",
  },
});
