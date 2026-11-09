import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import mockFixtures from "./mock-fixtures.js"; // TEMP

export default defineConfig({
  plugins: [react(), process.env.MOCK && mockFixtures()], // TEMP
  build: {
    rollupOptions: {
      // Libraries in their own long-cached chunk: an app update then re-downloads only our code.
      output: { manualChunks: { vendor: ["react", "react-dom", "leaflet"] } },
    },
  },
  server: {
    host: true, // reachable from a phone on the same Wi-Fi
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
