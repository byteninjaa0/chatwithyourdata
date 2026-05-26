import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  output: "standalone",
  // Keeps standalone deploys self-contained when copied outside a monorepo.
  outputFileTracingRoot: path.join(process.cwd()),
};

export default nextConfig;
