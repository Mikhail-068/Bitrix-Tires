import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendUrl = env.VITE_BACKEND_URL || "http://127.0.0.1:18080";

  return {
    plugins: [react()],
    server: {
      allowedHosts: [
        "списать-шины.рф",
        "www.списать-шины.рф",
        "xn----7sbxczhnck5d9ah.xn--p1ai",
        "www.xn----7sbxczhnck5d9ah.xn--p1ai",
      ],
      proxy: {
        "/api": {
          target: backendUrl,
          changeOrigin: true,
        },
      },
    },
  };
});
