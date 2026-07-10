import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `base` is baked in at build time (the agente pattern). In prod build with
// VITE_BASE=/pypoe-next/ (preview) or /pypoe/ (after cutover); dev defaults to
// "/". Everything in the app derives its API/WS URLs from import.meta.env.BASE_URL
// (see src/lib/api.js), so this single value drives the whole prefix — no
// separate VITE_API_URL / VITE_WS_URL needed.
//
// Dev-only proxy: point /api, /ws and the sidecar /auth OTP endpoints at the
// existing PyPoe backend + ac_auth so `npm run dev` behaves like prod behind
// the edge. Override the backend with GRAPHCHAT-style envs if needed.
const backend = process.env.PYPOE_DEV_API_TARGET || "http://127.0.0.1:8006";
const authSidecar = process.env.AUTH_SERVICE_BASE || "http://100.64.254.6:8009";

export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend, changeOrigin: true, ws: true },
      // OTP login endpoints go to the ac_auth sidecar, matching the edge.
      "/auth": { target: authSidecar, changeOrigin: true },
    },
  },
});
