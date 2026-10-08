import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: `npm run dev` here + `python -m quizz serve --reload` (API on :8000, proxied below).
// Prod: `npm run build` → dist/, served by FastAPI at http://localhost:8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  // Served from localhost: one ~170 kB gzipped bundle (markdown + highlighting) is fine.
  build: { chunkSizeWarningLimit: 1000 },
});
