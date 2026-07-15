import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_TARGET = process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": API_TARGET,
      "/chat": API_TARGET,
      "/rag": API_TARGET,
      "/knowledge-base": API_TARGET,
      "/tools": API_TARGET,
      "/tool-runs": API_TARGET,
      "/workflows": API_TARGET,
      "/memory": API_TARGET,
      "/runtime": API_TARGET,
      "/roles": API_TARGET,
      "/assets": API_TARGET,
      "/wechat": API_TARGET,
      "/news": API_TARGET,
      "/sessions": API_TARGET
    }
  }
});
