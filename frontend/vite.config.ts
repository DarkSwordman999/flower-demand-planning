import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// сборка кладётся в пакет бэкенда: FastAPI отдаёт её как веб-интерфейс
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/floraplan/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 2500,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
