import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Prevent Turbopack from inferring the wrong workspace root (multiple lockfiles).
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
