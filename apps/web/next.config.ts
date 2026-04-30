import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  distDir: process.env.NODE_ENV === "production" ? ".next-build" : ".next",
  reactStrictMode: true,
};

export default nextConfig;
