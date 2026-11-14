import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  agentRules: false,
  allowedDevOrigins: ["127.0.0.1"],
  reactStrictMode: true,
  experimental: {
    useTypeScriptCli: false,
  },
};

export default nextConfig;
