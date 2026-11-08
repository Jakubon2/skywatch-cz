import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import mockFixtures from "./mock-fixtures.js"; // TEMP

export default defineConfig({
  plugins: [react(), process.env.MOCK && mockFixtures()], // TEMP
  server: {
    host: true, // reachable from a phone on the same Wi-Fi
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
