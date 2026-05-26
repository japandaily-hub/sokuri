/**
 * 表示用フォーマットユーティリティ
 */

/**
 * 数値を日本円形式にフォーマットする。
 * @example formatPrice(12345) // "¥12,345"
 */
export function formatPrice(amount: number): string {
  return new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * ファイルサイズを人間が読みやすい形式に変換する。
 * @example formatFileSize(1536) // "1.5 KB"
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * ファイルを base64 文字列に変換する（data URI プレフィックスなし）。
 */
export function fileToBase64(file: File): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("FileReader result is not a string"));
        return;
      }
      // "data:image/jpeg;base64,<data>" → "<data>"
      const base64 = result.split(",")[1];
      if (base64 === undefined) {
        reject(new Error("base64 splitting failed"));
        return;
      }
      resolve(base64);
    };
    reader.onerror = () => reject(reader.error ?? new Error("FileReader error"));
    reader.readAsDataURL(file);
  });
}
