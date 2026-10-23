import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { "@": "/src" } },
    server: {
      port: 5173,
      strictPort: true,
      // Same-origin API in development, so the httpOnly refresh cookie works without CORS.
      proxy: { "/api": { target: env.VITE_API_PROXY ?? "http://127.0.0.1:8000", changeOrigin: false } },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
