import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev-only proxy so `npm run dev` can talk to a locally-running FastAPI
// backend (`uvicorn app.main:app` on :8000) without CORS setup. Not used
// in the production container, where FastAPI serves the built dist/
// directly (PRD §38.2).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
