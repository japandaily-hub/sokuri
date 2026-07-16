import type { Metadata } from "next";
import "./terms.css";
import { TermsTabs } from "./TermsTabs";

export const metadata: Metadata = {
  title: "利用規約",
  description:
    "カタヅケの利用規約です。ユーザー利用規約・業者利用規約について定めています。",
};

export default function TermsPage() {
  return (
    <main id="main">
      <section className="legal-hero">
        <div className="container">
          <span className="eyebrow">TERMS OF SERVICE</span>
          <h1>利用規約</h1>
          <p className="updated">制定・施行：2026年4月1日　最終改定：2026年6月25日</p>
        </div>
      </section>

      <TermsTabs />
    </main>
  );
}
