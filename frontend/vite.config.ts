import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API is the service on localhost:8000; in the container nginx proxies
// /api to it. The browser only ever talks to /api/public and /api/staff.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
