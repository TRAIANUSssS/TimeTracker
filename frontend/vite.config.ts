import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: Object.fromEntries(
      ["/stats", "/applications"].map((path) => [
        path,
        {
          target: "http://127.0.0.1:8765",
          changeOrigin: true,
          configure(proxy) {
            proxy.on("proxyReq", (request) => request.removeHeader("origin"));
          },
        },
      ]),
    ),
  },
  build: { target: "es2022" },
});
