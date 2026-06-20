import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone", // Minimal Docker image
  // Rewrite /api/* → FastAPI in the same Docker network
  async rewrites() {
    const apiUrl =
      process.env.NEXT_PUBLIC_API_URL ?? "http://api:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
      {
        source: "/healthz",
        destination: `${apiUrl}/healthz`,
      },
    ];
  },
};

export default nextConfig;
