import Link from "next/link";

/**
 * 承認待ち（vendor_status !== "active"）の業者に出す案内。
 * 承認には古物商許可証の画像提出が必須（admin API が未提出を 409 で拒否する）ため、
 * 未提出なら「やるべき事」としてプロフィールのアップロード導線を先頭に出す。
 * hasLicenseImage が null（取得前・不明）の時は一般的な案内だけを出す。
 */
/** ページごとに読み込む CSS が異なる（ダッシュボードは operator-shared.css を読まない）ため、装飾は部品側で完結させる。 */
const boxStyle: React.CSSProperties = {
  marginBottom: 20,
  padding: "12px 16px",
  background: "var(--warm, #fff8e6)",
  color: "var(--body, #333)",
  border: "1px solid var(--gold, #c9a227)",
  fontSize: 13.5,
  lineHeight: 1.75,
};

export function ApprovalPendingNotice({ hasLicenseImage }: { hasLicenseImage: boolean | null }) {
  if (hasLicenseImage === false) {
    return (
      <div className="op-alert warn" style={boxStyle} role="status">
        <strong>審査を進めるには古物商許可証の画像が必要です。</strong>
        <br />
        <Link href="/operator/profile" style={{ textDecoration: "underline", fontWeight: 600 }}>
          プロフィールから許可証の画像をアップロード
        </Link>
        すると運営が審査を開始します（通常3営業日以内）。承認後に入札できるようになります。案件の閲覧は承認前でも可能です。
      </div>
    );
  }
  return (
    <div className="op-alert warn" style={boxStyle} role="status">
      許可証を確認中です。運営による審査完了（通常3営業日以内）後に入札できるようになります。案件の閲覧は承認前でも可能です。
    </div>
  );
}
