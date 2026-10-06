/**
 * 画面にメールアドレスを出すときの伏せ字（React 非依存）。
 * 本人が「どのアドレスに届くか」を見分けられる最小限だけ出す: ローカル部は先頭1文字＋「***」、
 * ドメインはそのまま。形式が不正・空は null（呼び出し側で表示自体を省く）。
 */
export function maskEmail(email: string | null | undefined): string | null {
  if (typeof email !== "string") return null;
  const trimmed = email.trim();
  const at = trimmed.lastIndexOf("@");
  if (at < 1 || at === trimmed.length - 1) return null;
  const local = trimmed.slice(0, at);
  const domain = trimmed.slice(at + 1);
  if (/\s/.test(trimmed) || domain.indexOf(".") < 1) return null;
  const firstChar = Array.from(local)[0];
  return `${firstChar}***@${domain}`;
}
