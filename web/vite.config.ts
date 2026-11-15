import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // For `pnpm dev:vite` (HMR): run `wrangler dev` on :8788 alongside and log in there first.
  server: { proxy: { "/api": "http://localhost:8788", "/acceso": "http://localhost:8788" } },
});
