import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["192.168.0.182", "127.0.0.1", "learnloop.agenneer.com"],
  cacheComponents: true,
  partialPrefetching: true,
};

export default nextConfig;
