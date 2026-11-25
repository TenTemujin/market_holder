/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  // pool vmThreads: com forks/threads a suíte falhava de forma intermitente neste ambiente
  // ("Cannot read properties of undefined (reading config)" no describe); causa raiz não achada
  test: { environment: "node", include: ["src/**/*.test.ts"], pool: "vmThreads" },
});
