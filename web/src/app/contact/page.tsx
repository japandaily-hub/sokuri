"use client";

/** お問い合わせ（フォーム）。デザイン handoff: docs/design_handoff_katazuke/contact.html を忠実移植。
 *  ヘッダー/フッターは共通 SiteChrome が付与するため、ここでは <main id="main"> の中身のみ描画する。
 *  POST /contact（katadzuke-api.ts submitContactMessage）へ配線済み。422/429/5xx は日本語の
 *  案内に変換して表示し、失敗時に偽の完了表示は出さない（運営導線監査 r3-operator.md H1 是正）。 */

import { useState } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzApiError, submitContactMessage, toDisplayMessage } from "@/lib/katadzuke-api";
import "./contact.css";

type FieldId = "name" | "email" | "category" | "message";

const REQUIRED: FieldId[] = ["name", "email", "category", "message"];

const SUBMIT_FAILED_MESSAGE = "送信できませんでした。しばらくしてからもう一度お試しください。";

export default function ContactPage() {
  const [sent, setSent] = useState(false);
  const [sending, setSending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<FieldId, boolean>>({
    name: false,
    email: false,
    category: false,
    message: false,
  });

  function clearError(id: FieldId) {
    setErrors((prev) => (prev[id] ? { ...prev, [id]: false } : prev));
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (sending) return; // 二重送信防止
    const form = e.currentTarget;
    const next: Record<FieldId, boolean> = {
      name: false,
      email: false,
      category: false,
      message: false,
    };
    let ok = true;
    for (const id of REQUIRED) {
      const el = form.elements.namedItem(id) as
        | HTMLInputElement
        | HTMLSelectElement
        | HTMLTextAreaElement
        | null;
      if (!el || !el.value.trim()) {
        next[id] = true;
        ok = false;
      } else if (id === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(el.value.trim())) {
        // メール形式の検証（noValidate のためネイティブ検証は効かない）
        next[id] = true;
        ok = false;
      }
    }
    setErrors(next);
    if (!ok) return;

    const name = (form.elements.namedItem("name") as HTMLInputElement).value.trim();
    const email = (form.elements.namedItem("email") as HTMLInputElement).value.trim();
    const category = (form.elements.namedItem("category") as HTMLSelectElement).value;
    const message = (form.elements.namedItem("message") as HTMLTextAreaElement).value.trim();

    setSending(true);
    setSubmitError(null);
    try {
      await submitContactMessage({ name, email, category, message });
      setSent(true);
      if (typeof window !== "undefined") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    } catch (err) {
      if (err instanceof KdzApiError && err.status === 422) {
        setSubmitError("入力内容をご確認のうえ、もう一度お試しください。");
      } else if (err instanceof KdzApiError && err.status === 429) {
        setSubmitError("送信が集中しています。しばらく時間をおいて再度お試しください。");
      } else {
        setSubmitError(toDisplayMessage(err, SUBMIT_FAILED_MESSAGE));
      }
    } finally {
      setSending(false);
    }
  }

  return (
    <main id="main">
      {/* ============ ページヒーロー ============ */}
      <section className="page-hero">
        <div className="container">
          <span className="eyebrow">お問い合わせ</span>
          <h1>お問い合わせ</h1>
          <p>
            サービスに関するご質問・ご要望など、
            <br />
            お気軽にお問い合わせください。
          </p>
        </div>
      </section>

      {/* ============ フォーム ============ */}
      <div className="section tight">
        <div className="contact-wrap container">
          {/* LINE 優先案内 */}
          <div className="line-first">
            <div className="line-first-body">
              <strong>片付けを始めるなら、LINEが最短です</strong>
              <p>
                査定・出品のご依頼はLINEから。友だち追加するだけで、すぐに出品をはじめられます。
              </p>
            </div>
            <Link href="/login?callbackUrl=%2Fcreate" className="btn btn-line btn-lg">
              <Ic name="chat" />
              LINEではじめる
              <Ic name="arrow" />
            </Link>
          </div>

          <div className="or-divider">または、フォームからお問い合わせ</div>

          {/* フォームカード */}
          <div className="form-card" id="form">
            {!sent ? (
              <div id="form-body">
                <p className="form-section-label">お問い合わせフォーム</p>

                {submitError && (
                  <div className="auth-error" role="alert" style={{ marginBottom: 16 }}>
                    <svg
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                      style={{
                        width: 16,
                        height: 16,
                        fill: "none",
                        stroke: "var(--danger)",
                        strokeWidth: 2,
                        strokeLinecap: "round",
                        flexShrink: 0,
                      }}
                    >
                      <circle cx="12" cy="12" r="9" />
                      <path d="M12 8v4M12 16h.01" />
                    </svg>
                    {submitError}
                  </div>
                )}

                <form onSubmit={onSubmit} noValidate>
                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="name">
                        お名前<span className="req">必須</span>
                      </label>
                      <input
                        type="text"
                        id="name"
                        name="name"
                        placeholder="山田 花子"
                        autoComplete="name"
                        className={errors.name ? "has-error" : undefined}
                        onInput={() => clearError("name")}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="kana">
                        フリガナ<span className="opt">任意</span>
                      </label>
                      <input
                        type="text"
                        id="kana"
                        name="kana"
                        placeholder="ヤマダ ハナコ"
                        autoComplete="off"
                      />
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="email">
                      メールアドレス<span className="req">必須</span>
                    </label>
                    <input
                      type="email"
                      id="email"
                      name="email"
                      placeholder="example@email.com"
                      autoComplete="email"
                      inputMode="email"
                      className={errors.email ? "has-error" : undefined}
                      onInput={() => clearError("email")}
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="phone">
                      電話番号<span className="opt">任意</span>
                    </label>
                    <input
                      type="tel"
                      id="phone"
                      name="phone"
                      placeholder="090-0000-0000"
                      autoComplete="tel"
                    />
                  </div>

                  <div className="field">
                    <label htmlFor="category">
                      お問い合わせ種別<span className="req">必須</span>
                    </label>
                    <div className="select-wrap">
                      <select
                        id="category"
                        name="category"
                        defaultValue=""
                        className={errors.category ? "has-error" : undefined}
                        onChange={() => clearError("category")}
                      >
                        <option value="" disabled>
                          選択してください
                        </option>
                        <option value="service">サービスについて</option>
                        <option value="pricing">料金・費用について</option>
                        <option value="area">対応エリアについて</option>
                        <option value="privacy">個人情報の取り扱いについて</option>
                        <option value="trouble">トラブル・クレーム</option>
                        <option value="partner">業者登録・提携について</option>
                        <option value="press">取材・メディア掲載</option>
                        <option value="other">その他</option>
                      </select>
                    </div>
                  </div>

                  <div className="field">
                    <label htmlFor="message">
                      お問い合わせ内容<span className="req">必須</span>
                    </label>
                    <textarea
                      id="message"
                      name="message"
                      placeholder="ご質問・ご要望をできるだけ詳しくご記入ください。"
                      className={errors.message ? "has-error" : undefined}
                      onInput={() => clearError("message")}
                    />
                  </div>

                  <div className="submit-area">
                    <button type="submit" className="btn-submit" disabled={sending}>
                      <svg
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                        style={{
                          width: 20,
                          height: 20,
                          fill: "none",
                          stroke: "#fff",
                          strokeWidth: 1.9,
                          strokeLinecap: "round",
                          strokeLinejoin: "round",
                          flexShrink: 0,
                        }}
                      >
                        <path d="M22 2L11 13" />
                        <path d="M22 2L15 22l-4-9-9-4 20-7z" />
                      </svg>
                      {sending ? "送信中…" : "送信する"}
                    </button>
                    <p className="note">
                      送信いただいた内容は、通常3営業日以内にご返信します。
                      <br />
                      ご送信をもって
                      <Link href="/privacy">プライバシーポリシー</Link>
                      に同意したものとみなします。
                    </p>
                  </div>
                </form>
              </div>
            ) : (
              /* 送信完了 */
              <div className="thanks" id="thanks">
                <div className="thanks-ic">
                  <svg
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                    style={{
                      width: 32,
                      height: 32,
                      fill: "none",
                      stroke: "var(--blue)",
                      strokeWidth: 2,
                      strokeLinecap: "round",
                      strokeLinejoin: "round",
                    }}
                  >
                    <circle cx="12" cy="12" r="9" />
                    <path d="M8 12l2.5 2.5L16 9" />
                  </svg>
                </div>
                <h3>送信を受け付けました</h3>
                <p>
                  お問い合わせありがとうございます。
                  <br />
                  3営業日以内に登録メールアドレスへご連絡します。
                </p>
                <Link href="/" className="btn btn-ghost btn-lg">
                  トップページへ戻る
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
