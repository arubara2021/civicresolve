import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cache Components (partial prerendering) triggers a dev-mode InvariantError
  // on fully client-rendered routes in Next 16.4. Disabled for this project.
  cacheComponents: false,
};

export default nextConfig;