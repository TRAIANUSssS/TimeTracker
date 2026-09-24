import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 6970,
    strictPort: true,
    proxy: Object.fromEntries(
      [
        "/stats",
        "/applications",
        "/settings/preferences",
        "/settings/collection",
        "/settings/display",
        "/settings/recording",
      ].map((path) => [
        path,
        {
          target: "http://127.0.0.1:6969",
          changeOrigin: true,
          bypass(request) {
            if (
              request.method === "GET" &&
              ["/settings/display", "/settings/recording"].includes(
                request.url || "",
              )
            )
              return "/index.html";
          },
          configure(proxy) {
            proxy.on("proxyReq", (request) => request.removeHeader("origin"));
          },
        },
      ]),
    ),
  },
  build: { target: "es2022" },
});
