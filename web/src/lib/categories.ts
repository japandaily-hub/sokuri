/** 業者の取扱カテゴリ（id はバックエンド保存値・name は表示名）。業者プロフィール編集画面と公開プロフィールで共有する。 */
export const VENDOR_CATEGORY_NAMES: Record<string, string> = {
  kaden: "家電・PC",
  brand: "ブランド品",
  camera: "カメラ",
  watch: "時計・宝飾",
  fashion: "衣類・靴",
  furniture: "家具",
  game: "ゲーム・玩具",
  hobby: "楽器・趣味",
  other: "その他",
};

/** id → 表示名。未知の id はそのまま返す（表示が空になるより保守的）。 */
export function vendorCategoryName(id: string): string {
  return VENDOR_CATEGORY_NAMES[id] ?? id;
}

/** 訪問予定の表示。候補日ラベルに日付が含まれていれば ISO 日付を重ねて出さない。 */
export function formatVisitSchedule(visitDate: string | null | undefined, rawSlot: string | null | undefined): string {
  // 業者の自由入力なので、表示をねじる制御文字（ゼロ幅・双方向制御）は落とす
  const slot = rawSlot ? rawSlot.replace(/[​-‏‪-‮⁦-⁩]/g, "") : rawSlot;
  if (slot && /\d+月\d+日/.test(slot)) return slot;
  if (!visitDate) return slot ?? "";
  const d = new Date(`${visitDate}T00:00:00`);
  const label = Number.isNaN(d.getTime())
    ? visitDate
    : `${d.getMonth() + 1}月${d.getDate()}日（${["日", "月", "火", "水", "木", "金", "土"][d.getDay()]}）`;
  return slot ? `${label} ${slot}` : label;
}
