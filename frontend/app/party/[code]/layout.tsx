import type { Metadata } from 'next';

// Party links are private: keep them out of search engines.
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function PrivateRoomLayout({ children }: { children: React.ReactNode }) {
  return children;
}
