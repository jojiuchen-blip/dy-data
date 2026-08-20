import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    maxWorkers: 1,
    setupFiles: "./src/test/setup.js",
  },
});
