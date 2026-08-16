/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const host = process.env.DESINFO_API_HOST || "127.0.0.1";
    const port = process.env.DESINFO_API_PORT || "8700";
    // /api/export is handled by src/app/api/export/route.ts (HMAC proxy).
    return [
      {
        source: "/api/meta",
        destination: `http://${host}:${port}/api/meta`,
      },
      {
        source: "/api/ranking",
        destination: `http://${host}:${port}/api/ranking`,
      },
      {
        source: "/api/gov",
        destination: `http://${host}:${port}/api/gov`,
      },
      {
        source: "/health",
        destination: `http://${host}:${port}/health`,
      },
    ];
  },
};

module.exports = nextConfig;
