const backend = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || 'http://api:8000';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  outputFileTracing: false,
  images: { unoptimized: true },
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
  trailingSlash: false,
  async rewrites() {
    return [
      { source: '/admin/api/:path*', destination: `${backend}/admin/api/:path*` },
      { source: '/login', destination: `${backend}/login` },
      { source: '/logout', destination: `${backend}/logout` },
      { source: '/webhooks/:path*', destination: `${backend}/webhooks/:path*` },
      { source: '/health', destination: `${backend}/health` }
    ];
  }
};

export default nextConfig;
