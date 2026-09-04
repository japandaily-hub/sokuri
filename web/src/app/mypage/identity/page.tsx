"use client";

/**
 * 本人確認（/mypage/identity）。
 * 提出は任意。利用目的は「なりすまし・不正出品の防止、および運営からの本人確認」であり、
 * 古物営業法第15条の確認義務は訪問する古物商（業者）が負うものでカタヅケの義務ではない。
 * 提出書類を業者へ渡すことはないため、当社の法定義務であるかのような表現は用いない。
 * 提出書類は運営（admin）が審査し、承認/差し戻しを行う（/admin/identity-documents）。
 *
 * デザインは既存の /mypage/profile（人の森整合テーマ: 明朝・角丸0・トークン色）を踏襲する。
 * 独自の form-card / edit-section-title は profile.css と同一の見た目になるよう
 * このページ専用スコープ（.identity-page）で再定義する（既存ページの慣習に合わせ、
 * ページ間でのクラス共有はしない）。
 *
 * バックエンド: GET /users/me/identity, POST /users/me/identity-documents（multipart）,
 * GET /users/me/identity-documents/{id}/file?side=（Blob。<img src> 直参照不可）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AppHeader } from "@/components/kdz/AppHeader";
import { StatusBadge, useToken } from "@/components/kdz/Ui";
import {
  getMyIdentity,
  getMyProfile,
  uploadIdentityDocument,
  fetchMyIdentityDocumentBlob,
  toDisplayMessage,
  IDENTITY_STATUS_LABEL,
  IDENTITY_DOC_TYPES,
  type IdentityOut,
  type IdentityDocType,
  type UserProfile,
} from "@/lib/katadzuke-api";
import "./identity.css";

const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const MAX_BYTES = 10 * 1024 * 1024;

const ICON_SHIELD = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 3l7 3v6c0 4.7-3 7.9-7 9-4-1.1-7-4.3-7-9V6z" />
    <path d="M9 12l2 2 4-4" />
  </svg>
);
const ICON_UP = (
  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
    <path d="M12 19V6M6 12l6-6 6 6" />
  </svg>
);

function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      style={{
        marginBottom: 20,
        padding: "12px 16px",
        borderRadius: "var(--radius-s)",
        background: "rgba(215,0,53,.06)",
        color: "var(--danger)",
        fontSize: 13,
        border: "1px solid rgba(215,0,53,.35)",
      }}
    >
      {children}
    </div>
  );
}

/** 選択済み/取得済み画像の小サムネイル表示。Blob URL の生成・破棄は呼び出し側が行う。 */
function ImageThumb({ label, src }: { label: string; src: string | null }) {
  return (
    <div className="doc-thumb">
      <div className="doc-thumb-frame">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={`${label}のプレビュー`} />
        ) : (
          <span className="doc-thumb-empty">未選択</span>
        )}
      </div>
      <span className="doc-thumb-label">{label}</span>
    </div>
  );
}

export default function IdentityPage() {
  const { token, loading: tokenLoading } = useToken();

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [identity, setIdentity] = useState<IdentityOut | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 提出フォーム
  const [docType, setDocType] = useState<IdentityDocType>(IDENTITY_DOC_TYPES[0].id);
  const [frontFile, setFrontFile] = useState<File | null>(null);
  const [backFile, setBackFile] = useState<File | null>(null);
  const [frontPreview, setFrontPreview] = useState<string | null>(null);
  const [backPreview, setBackPreview] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const frontInputRef = useRef<HTMLInputElement | null>(null);
  const backInputRef = useRef<HTMLInputElement | null>(null);

  // 提出済み画像（本人確認用のサムネイル。認証必須のため Blob 経由で取得）
  const [submittedFrontUrl, setSubmittedFrontUrl] = useState<string | null>(null);
  const [submittedBackUrl, setSubmittedBackUrl] = useState<string | null>(null);
  const [submittedImagesLoading, setSubmittedImagesLoading] = useState(false);

  const docTypeConfig = IDENTITY_DOC_TYPES.find((d) => d.id === docType) ?? IDENTITY_DOC_TYPES[0];

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [p, i] = await Promise.all([getMyProfile(token), getMyIdentity(token)]);
      setProfile(p);
      setIdentity(i);
      setLoadError(null);
    } catch (e) {
      setLoadError(toDisplayMessage(e, "本人確認状況の取得に失敗しました"));
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  // 提出済み画像の取得（document_id が確定したら都度取り直す）
  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    async function run() {
      if (!token || !identity?.document_id) {
        setSubmittedFrontUrl(null);
        setSubmittedBackUrl(null);
        return;
      }
      setSubmittedImagesLoading(true);
      try {
        const frontBlob = await fetchMyIdentityDocumentBlob(identity.document_id, "front", token);
        if (cancelled) return;
        const frontUrl = URL.createObjectURL(frontBlob);
        urls.push(frontUrl);
        setSubmittedFrontUrl(frontUrl);
        if (identity.has_back) {
          const backBlob = await fetchMyIdentityDocumentBlob(identity.document_id, "back", token);
          if (cancelled) return;
          const backUrl = URL.createObjectURL(backBlob);
          urls.push(backUrl);
          setSubmittedBackUrl(backUrl);
        } else {
          setSubmittedBackUrl(null);
        }
      } catch {
        // 提出済み画像の表示は補助情報のため、失敗してもフォーム自体は使えるようにする。
        setSubmittedFrontUrl(null);
        setSubmittedBackUrl(null);
      } finally {
        if (!cancelled) setSubmittedImagesLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [token, identity?.document_id, identity?.has_back]);

  // 選択ファイルのプレビュー URL 管理
  useEffect(() => {
    if (!frontFile) {
      setFrontPreview(null);
      return;
    }
    const url = URL.createObjectURL(frontFile);
    setFrontPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [frontFile]);
  useEffect(() => {
    if (!backFile) {
      setBackPreview(null);
      return;
    }
    const url = URL.createObjectURL(backFile);
    setBackPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [backFile]);

  function pickFile(file: File | null, side: "front" | "back") {
    if (file) {
      if (!ALLOWED_TYPES.includes(file.type)) {
        setSubmitError("JPG・PNG・WEBP形式の画像を選択してください");
        return;
      }
      if (file.size > MAX_BYTES) {
        setSubmitError("ファイルサイズは10MBまでです");
        return;
      }
    }
    setSubmitError(null);
    if (side === "front") setFrontFile(file);
    else setBackFile(file);
  }

  function onChangeDocType(next: IdentityDocType) {
    setDocType(next);
    setBackFile(null);
    if (backInputRef.current) backInputRef.current.value = "";
    setSubmitError(null);
  }

  async function onSubmit() {
    if (!token || submitting) return;
    if (!profile?.birth_date) {
      setSubmitError("先にプロフィールで生年月日を登録してください");
      return;
    }
    if (!frontFile) {
      setSubmitError("表面の画像を選択してください");
      return;
    }
    if (docTypeConfig.backRequired && !backFile) {
      setSubmitError("裏面の画像を選択してください");
      return;
    }
    if (docTypeConfig.backRequired && backFile && backFile.size === 0) {
      setSubmitError("裏面の画像を選択してください");
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const result = await uploadIdentityDocument(
        { docType, front: frontFile, back: docTypeConfig.backRequired ? backFile : null },
        token,
      );
      setIdentity(result);
      setFrontFile(null);
      setBackFile(null);
      if (frontInputRef.current) frontInputRef.current.value = "";
      if (backInputRef.current) backInputRef.current.value = "";
      setSubmitted(true);
      window.setTimeout(() => setSubmitted(false), 2500);
    } catch (e) {
      setSubmitError(toDisplayMessage(e, "提出に失敗しました。時間をおいて再度お試しください。"));
    } finally {
      setSubmitting(false);
    }
  }

  const sessionExpired = !tokenLoading && !token;

  if (sessionExpired) {
    return (
      <div className="identity-page">
        <AppHeader />
        <main id="main">
          <div className="identity-wrap">
            <ErrorBanner>
              セッションが切れました。再ログインしてください。
              <Link href="/login" style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline" }}>
                ログインへ
              </Link>
            </ErrorBanner>
          </div>
        </main>
      </div>
    );
  }

  if (tokenLoading || (!identity && !loadError)) {
    return (
      <div className="identity-page">
        <AppHeader />
        <main id="main">
          <div className="identity-wrap" style={{ textAlign: "center", padding: "60px 20px", color: "var(--body-soft)" }}>
            読み込み中…
          </div>
        </main>
      </div>
    );
  }

  if (!identity) {
    return (
      <div className="identity-page">
        <AppHeader />
        <main id="main">
          <div className="identity-wrap">
            <ErrorBanner>
              {loadError ?? "本人確認状況の取得に失敗しました"}
              <button
                type="button"
                onClick={() => void load()}
                style={{ marginLeft: 8, fontWeight: 600, textDecoration: "underline", background: "none", border: "none", color: "inherit", cursor: "pointer" }}
              >
                再読み込み
              </button>
            </ErrorBanner>
          </div>
        </main>
      </div>
    );
  }

  const canSubmit = identity.status === "unverified" || identity.status === "rejected";
  const needsBirthDate = !profile?.birth_date;

  return (
    <div className="identity-page">
      <AppHeader />
      <main id="main">
        <div className="identity-wrap">
          {loadError ? <ErrorBanner>{loadError}</ErrorBanner> : null}

          <div className="edit-section-title">
            {ICON_SHIELD}
            本人確認
          </div>

          {/* 状態カード */}
          <div className="form-card">
            <div className="id-status-row">
              <StatusBadge
                value={identity.status === "approved" ? "approved" : identity.status}
                label={IDENTITY_STATUS_LABEL[identity.status]}
              />
              {identity.submitted_at ? (
                <span className="id-status-sub">
                  提出日時: {new Date(identity.submitted_at).toLocaleString("ja-JP")}
                </span>
              ) : null}
            </div>
            {identity.status === "pending" ? (
              <p className="id-status-desc">
                運営が提出書類を確認しています。審査完了までしばらくお待ちください。
              </p>
            ) : null}
            {identity.status === "approved" ? (
              <p className="id-status-desc">本人確認が完了しています。再提出の必要はありません。</p>
            ) : null}
            {identity.status === "rejected" ? (
              <p className="id-status-desc id-status-rejected">
                差し戻し理由: {identity.reject_reason ?? "確認できませんでした。書類を確認のうえ再提出してください。"}
              </p>
            ) : null}
            {identity.status === "unverified" ? (
              <p className="id-status-desc">
                まだ本人確認書類が提出されていません。ご提出は任意です。いただいた書類は、なりすまし・不正出品の防止、および運営からの本人確認のために利用します。
              </p>
            ) : null}

            {(identity.status === "pending" ||
              identity.status === "approved" ||
              identity.status === "rejected") &&
            identity.document_id ? (
              <div className="doc-thumb-row">
                {submittedImagesLoading ? (
                  <span className="id-status-sub">提出済み画像を読み込み中…</span>
                ) : (
                  <>
                    <ImageThumb label="表面" src={submittedFrontUrl} />
                    {identity.has_back ? <ImageThumb label="裏面" src={submittedBackUrl} /> : null}
                  </>
                )}
              </div>
            ) : null}
          </div>

          {/* 注意事項 */}
          <div className="id-notice-box">
            <ul>
              <li>ご提出は任意です。いただいた書類・生年月日・職業は、なりすまし・不正出品の防止、および運営からの本人確認のために利用し、業者へお渡しすることはありません。</li>
              <li>訪問時に、業者から古物営業法に基づく本人確認（住所・氏名・職業・年齢の確認のための身分証のご提示）を求められることがあります。買取金額が1万円以上の場合のほか、ゲームソフト・CD/DVD・書籍・バイク等の一部の品目は、金額にかかわらず確認の対象です。</li>
              <li>有効期限内の書類をご提出ください。</li>
              <li>書類に記載の住所が、プロフィールに登録した住所と一致している必要があります。</li>
              <li>健康保険証は住所記載がない場合があるため、承認できないことがあります。</li>
            </ul>
          </div>

          {/* 提出フォーム */}
          {canSubmit ? (
            needsBirthDate ? (
              <div className="form-card">
                <p style={{ fontSize: 13, color: "var(--body-soft)", lineHeight: 1.75, margin: 0 }}>
                  本人確認書類を提出する前に、プロフィールで生年月日を登録してください。
                </p>
                <Link href="/mypage/profile" className="btn btn-primary" style={{ marginTop: 12, display: "inline-flex" }}>
                  プロフィールを編集する
                </Link>
              </div>
            ) : (
              <div className="form-card">
                {submitError ? <div className="pw-change-error">{submitError}</div> : null}

                <div className="field">
                  <label htmlFor="inp-doc-type">
                    書類種別<span className="req">必須</span>
                  </label>
                  <select
                    id="inp-doc-type"
                    value={docType}
                    onChange={(e) => onChangeDocType(e.target.value as IdentityDocType)}
                  >
                    {IDENTITY_DOC_TYPES.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.label}
                      </option>
                    ))}
                  </select>
                  {docTypeConfig.note ? <div className="field-hint">{docTypeConfig.note}</div> : null}
                </div>

                <div className="row-2">
                  <div className="field">
                    <label htmlFor="inp-front">
                      表面<span className="req">必須</span>
                    </label>
                    <input
                      ref={frontInputRef}
                      type="file"
                      id="inp-front"
                      accept="image/jpeg,image/png,image/webp"
                      onChange={(e) => pickFile(e.target.files?.[0] ?? null, "front")}
                    />
                    <ImageThumb label="表面プレビュー" src={frontPreview} />
                  </div>
                  <div className="field">
                    <label htmlFor="inp-back">
                      裏面
                      {docTypeConfig.backRequired ? (
                        <span className="req">必須</span>
                      ) : (
                        <span className="opt">不要</span>
                      )}
                    </label>
                    <input
                      ref={backInputRef}
                      type="file"
                      id="inp-back"
                      accept="image/jpeg,image/png,image/webp"
                      disabled={!docTypeConfig.backRequired}
                      onChange={(e) => pickFile(e.target.files?.[0] ?? null, "back")}
                    />
                    {docTypeConfig.backRequired ? (
                      <ImageThumb label="裏面プレビュー" src={backPreview} />
                    ) : (
                      <div className="field-hint">この書類は裏面の提出は不要です</div>
                    )}
                  </div>
                </div>

                <button
                  type="button"
                  className="btn btn-primary"
                  style={{ width: "100%", marginTop: 6 }}
                  onClick={() => void onSubmit()}
                  disabled={submitting}
                >
                  {submitting ? (
                    <>
                      <span className="spinning">↻</span> 提出中…
                    </>
                  ) : submitted ? (
                    "提出しました ✓"
                  ) : (
                    <>{ICON_UP} 本人確認書類を提出する</>
                  )}
                </button>
              </div>
            )
          ) : null}

          <div style={{ marginTop: 4 }}>
            <Link href="/mypage/profile" className="id-back-link">
              ← マイページ・設定にもどる
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
