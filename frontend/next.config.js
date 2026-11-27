/** @type {import('next').NextConfig} */
module.exports = {
  // Private party and host pages also send a header, for crawlers that skip meta tags.
  async headers() {
    const noindex = [{ key: 'X-Robots-Tag', value: 'noindex, nofollow' }];
    return [
      { source: '/party/:path*', headers: noindex },
      { source: '/host/:path*', headers: noindex },
    ];
  },
};
