import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/",
  plugins: [react()],
  build: {
    outDir: "../mnemo_memory/interfaces/web_assets",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false
  }
});
