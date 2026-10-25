import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";
const repoName = "resilent-multi-domain-sdn";

const nextConfig: NextConfig = {
  output: "export",
  // basePath and assetPrefix for GitHub Pages project site
  basePath: isProd ? `/${repoName}` : "",
  assetPrefix: isProd ? `/${repoName}/` : "",
  images: {
    unoptimized: true,
  },
  // Note: cacheComponents/partialPrefetching (PPR) cannot be used with output:"export"
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
