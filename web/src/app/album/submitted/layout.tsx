import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "アルバム受付完了",
  robots: { index: false, follow: false },
};

export default function AlbumSubmittedLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
