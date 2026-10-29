import type { NextConfig } from "next";

// Tauri loads the static export from `out/`; there is no Node server at runtime.
const config: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
};

export default config;
