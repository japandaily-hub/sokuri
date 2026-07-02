/**
 * 連絡先（住所）開示ルールの明記バナー。
 * デザインは既存の hint-banner パターン（signup/page.tsx 等）に合わせ、
 * 背景 --pale・アイコン --blue・本文 --body の淡色バナーで表示する。
 * Tailwind ベースのページ（operator/cases/[id] 等）からも独自CSSページ
 * （applications 等）からも共通で使えるよう、インラインスタイルで
 * katazuke.css のカラートークン（CSS変数）を直接参照する。
 */

import { Ic } from "@/components/kdz/Icons";

export type DisclosureNoticeProps = {
  /** この画面を見ている当事者。文言の主語を切り替える。 */
  viewer: "user" | "operator";
  /** 開示済みか（成約成立済み && !awaitingApproval）。 */
  disclosed: boolean;
  /** 承認待ちで非開示中か（limited業者が落札し、運営の admin 承認待ちのケース）。 */
  awaitingApproval?: boolean;
};

function resolveMessage({
  viewer,
  disclosed,
  awaitingApproval,
}: DisclosureNoticeProps): string {
  if (disclosed) {
    return viewer === "operator"
      ? "お客様との成約が成立しています。訪問のため、住所と連絡先が共有されています。"
      : "業者との成約が成立しています。訪問のため、住所と連絡先が共有されています。";
  }
  if (awaitingApproval) {
    return viewer === "operator"
      ? "運営による登録審査が完了するまで、お客様の住所は表示されません。審査完了後、自動的に開示されます。"
      : "運営がこの業者の登録内容を確認中のため、まだ住所は共有されていません。";
  }
  return viewer === "operator"
    ? "住所の詳細は、お客様があなたを選んで成約が成立した時点で開示されます。"
    : "業者へ住所が伝わるのは、1社を選んで成約した後だけです。";
}

/** 連絡先開示ルールの明記バナー（hint-banner 意匠）。 */
export function DisclosureNotice(props: DisclosureNoticeProps) {
  const message = resolveMessage(props);
  return (
    <div
      style={{
        background: "var(--pale)",
        borderRadius: "var(--radius-s)",
        padding: "14px 18px",
        fontSize: 13,
        color: "var(--body)",
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        lineHeight: 1.75,
      }}
    >
      <Ic
        name="shield"
        style={{ color: "var(--blue)", flexShrink: 0, marginTop: 1, width: 16, height: 16 }}
      />
      <span>{message}</span>
    </div>
  );
}
