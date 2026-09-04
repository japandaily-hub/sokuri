"""案件 AI サマリー生成 — 既存 vision.analyze_image（Gemini Vision）を流用する。

案件写真の商品ごとのアルバム化に伴い、以下2系統の生成関数を提供する:
- ``generate_case_summary``: 既存関数。シグネチャ・挙動は完全に温存する
  （未分類写真グループ用として引き続き使用。既存テストは無改修で通ること）。
- ``analyze_item`` / ``generate_case_ai``: 商品（CaseItem）単位のAI解析を行う新規関数。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from app.db.models.enums import ItemCondition
from app.services import storage
from app.services.text_sanitize import normalize_and_strip_control_chars
from app.services.vision import analyze_image

logger = logging.getLogger(__name__)

_MAX_PHOTOS_FOR_AI = 4
# cases.py（レガシー経路）が base64 化の枚数を絞るための公開エイリアス。
MAX_PHOTOS_FOR_AI = _MAX_PHOTOS_FOR_AI
# Gemini呼び出し（analyze_image）1回あたりのタイムアウト。無応答のままイベント
# ループを塞ぎ続け、案件作成リクエスト全体が長時間ハングするのを防ぐ
# （security review 指摘対応: コストDoS/可用性）。写真解析は既存の try/except
# で継続前提のため、タイムアウトも同じフォールバック経路（当該写真をスキップ）
# にそのまま乗る。
_ANALYZE_IMAGE_TIMEOUT_SEC = 25
# ai_summary は全業者（承認前アカウント含む）に配信されるため、単一属性値の長さと
# 最終文字列の長さの両方に上限を設ける（security review Medium-2対応: 画像内に
# 長文を印字してアップロードするとGemini経由でDBカラム・UIが肥大化しうる）。
_MAX_ATTR_LEN = 40
_MAX_SUMMARY_LEN = 500

# 傷・色あせ・凹みなど状態注記が必要なコンディション。
_NOTABLE_CONDITIONS = {ItemCondition.FAIR, ItemCondition.POOR}

# 属性値として許容する文字種（日本語・英数字・空白・一般的な記号のみ）。
_ATTR_ALLOWED_RE = re.compile(r"^[\w\s぀-ヿ一-鿿\-.()/]{1,%d}$" % _MAX_ATTR_LEN)
# URL・連絡先・命令文らしき文字列を弾くための簡易シグナル。
_ATTR_SUSPICIOUS_RE = re.compile(r"https?://|www\.|@|\.(com|net|jp|org|io)\b", re.IGNORECASE)


def _safe_attr(value: object) -> str | None:
    """Gemini由来の属性値(brand/model_name)を業者表示用に無害化する。

    画像内に印字された任意の文字列（偽装ブランドラベル等）がGeminiの構造化
    出力を経由してそのまま「AI要約」として全業者に配信されるのを防ぐ
    （security review Medium-1対応: 間接プロンプトインジェクション/なりすまし
    コンテンツ注入の緩和）。プロンプト側の指示（vision.pyのrule 6）だけに
    依存せず、ここでも機械的に検証する多層防御とする。
    """
    if not value:
        return None
    # NFKC正規化 + 制御文字・Unicode双方向制御文字の除去(表示崩れ・なりすまし対策)。
    text = normalize_and_strip_control_chars(str(value))
    if not text:
        return None
    if not _ATTR_ALLOWED_RE.match(text):
        return None
    if _ATTR_SUSPICIOUS_RE.search(text):
        return None
    return text


def _fallback_summary(
    purpose: str,
    housing_type: str | None,
    floor_plan: str | None,
    photo_count: int,
) -> str:
    parts = [f"利用目的: {purpose}。"]
    if housing_type:
        parts.append(f"住居: {housing_type}")
        if floor_plan:
            parts.append(f"（{floor_plan}）")
        parts.append("。")
    parts.append(f"写真 {photo_count} 枚。詳細は写真を確認してください。")
    return "".join(parts)


async def _detect_photo_labels(photo_urls: list[str], max_photos: int) -> list[str]:
    """写真群からラベル（brand/model/状態注記込み）の一覧を検出する。

    ``generate_case_summary``（未分類写真グループ）と ``generate_case_ai``
    （商品未紐づけの ungrouped_refs）の両方から呼ばれる共通ロジック。
    元は ``generate_case_summary`` のインライン実装だったものを、挙動を一切
    変えずに抽出したもの（DRY是正。generate_case_summary側の出力は本抽出の
    前後で1バイトも変わらない）。
    """
    detected: list[str] = []
    for url in photo_urls[:max_photos]:
        try:
            async with asyncio.timeout(_ANALYZE_IMAGE_TIMEOUT_SEC):
                result = await analyze_image(url)
            label = result.detected_name or result.detected_category_label
            if not label:
                continue
            notes: list[str] = []
            for raw_value in (result.attributes.get("brand"), result.attributes.get("model_name")):
                value = _safe_attr(raw_value)
                if value and value not in label and value not in notes:
                    notes.append(value)
            if result.initial_condition in _NOTABLE_CONDITIONS:
                notes.append("状態: 傷・使用感あり")
            if notes:
                label = f"{label}（{'、'.join(notes)}）"
            detected.append(label)
        except Exception as exc:
            # 例外オブジェクトを直接%sで文字列化しない（SDKの例外に画像データや
            # リクエスト内容が含まれる可能性を考慮し、型名+切り詰めのみ記録）。
            logger.warning(
                "summary: 写真解析に失敗（continue）- %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            continue
    return detected


async def generate_case_summary(
    *,
    purpose: str,
    housing_type: str | None,
    floor_plan: str | None,
    photo_urls: list[str],
    photo_count: int | None = None,
) -> str:
    """写真群から案件サマリーを生成する。AI 不可時もフォールバック文を返す。"""
    detected = await _detect_photo_labels(photo_urls, _MAX_PHOTOS_FOR_AI)

    base = _fallback_summary(
        purpose, housing_type, floor_plan,
        photo_count if photo_count is not None else len(photo_urls),
    )
    if not detected:
        return base
    items = "、".join(dict.fromkeys(detected))
    summary = f"{base} AI 検出品目: {items}。"
    if len(summary) > _MAX_SUMMARY_LEN:
        summary = summary[:_MAX_SUMMARY_LEN].rstrip() + "…"
    return summary


def _read_and_encode_data_url(path) -> str:  # type: ignore[no-untyped-def]
    """ファイルを読み込み base64 データ URL 文字列を組み立てる（同期・CPU/IOバウンド）。

    ``photo_url_for_ai`` から ``asyncio.to_thread`` 経由でのみ呼び出すこと
    （イベントループを塞がないため）。
    """
    import base64

    ext = path.suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


async def photo_url_for_ai(storage_key: str, raw_url: str | None) -> str | None:
    """AI に渡す画像参照を決める。ローカル保存ファイルは base64 データ URL 化する。

    ファイル読み込み + base64エンコードは同期I/O・CPUバウンドのため
    ``asyncio.to_thread`` でスレッドへ逃がし、イベントループをブロックしない
    （security review 指摘対応。呼び出し元は「実際に解析対象となる写真のみ」
    このタイミングで遅延呼び出しすること。全写真を先行してbase64化しない）。
    """
    path = storage.file_path(storage_key)
    if path is not None:
        return await asyncio.to_thread(_read_and_encode_data_url, path)
    if raw_url and raw_url.startswith("https://"):
        # R3再レビュー Medium対応: vision.analyze_image は security review N-7
        # 対応（SSRF対策）により https:// URL の受け付けを全面撤廃済みのため、
        # ここで raw_url をそのまま返すと呼び出し先で必ず ValueError になり、
        # 到達すれば無意味な Gemini 呼び出し試行（＋タイムアウト待ち）だけが
        # 発生する。呼び出し元（analyze_item/_detect_photo_labels）は例外を
        # 握り潰して継続する設計のため案件作成自体は失敗しないが、意図が
        # 不明瞭な死んだ分岐のため、ここで明示的に AI 解析をスキップする
        # （None を返す＝「解析対象から除外」。案件作成は継続）。
        logger.warning(
            "photo_url_for_ai: storage_key=%s の実体を解決できず、raw_url が "
            "https のため AI 解析をスキップします（vision.analyze_image は "
            "https を受け付けない設計）。",
            storage_key,
        )
        return None
    return None


# ──────────────────────────── 商品（CaseItem）単位のAI解析 ────────────────────────────
#
# 案件写真の商品ごとのアルバム化に伴う新規関数群。Bid/Transaction の単位（1案件）は
# 変更しない。撮影・AI解析・表示のみを商品（CaseItem）単位に整理する。

# 商品1点あたり解析する代表写真の最大枚数（1枚目=代表、2枚目=傷/タグの寄り）。
_MAX_PHOTOS_PER_ITEM_ANALYSIS = 2
# 案件1件あたりのGemini呼び出し総数の上限（items側予算。ungrouped_refs側の
# _MAX_PHOTOS_FOR_AI とは独立した別枠）。
_MAX_GEMINI_CALLS_PER_CASE = 8
# 商品解析タスクの最大同時実行数。
_MAX_CONCURRENT_ITEM_ANALYSIS = 3
# CaseItem.ai_summary の文字数上限。
_MAX_ITEM_SUMMARY_LEN = 200


#: (storage_key, url) の生タプル。AI解析用の実体参照（base64データURL化等）は
#: 実際に解析対象へ割り当てられた後にのみ ``photo_url_for_ai`` で遅延生成する。
RawPhotoRef = tuple[str, "str | None"]


@dataclass
class ItemAnalysisInput:
    """generate_case_ai への入力: 商品1件分のユーザー入力名と解析対象候補写真の参照。

    ``photo_refs`` は (storage_key, url) の生タプル列（sort_order 昇順。先頭
    最大2枚のみが解析対象候補になる）。**ここではまだ base64 データURL化しない**
    （全写真を先行してbase64化するとメモリ/CPUを無駄に消費するため。
    security review 指摘対応）。実体解決は ``_analyze_items_with_budget`` 内で
    予算配分（どの写真が実際に解析されるか）が確定した後に行う。
    """

    name: str | None
    photo_refs: list[RawPhotoRef]


@dataclass
class ItemAnalysisResult:
    """商品1件分のAI解析結果（CaseItem.ai_detected_name/ai_condition/ai_summary に対応）。"""

    ai_detected_name: str | None = None
    ai_condition: ItemCondition | None = None
    ai_summary: str | None = None


async def analyze_item(
    *, photo_refs: list[str]
) -> tuple[str | None, ItemCondition | None, str | None]:
    """商品1点の代表写真（最大2枚: 1枚目=代表、2枚目=傷/タグの寄り）を解析する。

    Returns:
        ``(ai_detected_name, ai_condition, ai_summary)``。全写真の解析に失敗した
        場合、または detected_name/detected_category_label が_safe_attrで
        いずれもサニタイズ不能だった場合は ``(None, None, None)``。
    """
    detected_name: str | None = None
    condition: ItemCondition | None = None
    notes: list[str] = []
    notable = False

    for ref in photo_refs[:_MAX_PHOTOS_PER_ITEM_ANALYSIS]:
        try:
            async with asyncio.timeout(_ANALYZE_IMAGE_TIMEOUT_SEC):
                result = await analyze_image(ref)
        except Exception as exc:
            # 画像データ・リクエスト内容の漏洩防止のため型名+切り詰めのみ記録
            # （generate_case_summary と同じ書き方を踏襲）。
            logger.warning(
                "summary: 商品写真解析に失敗（continue）- %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            continue

        if detected_name is None:
            # Gemini由来の検出名は必ず_safe_attrでサニタイズしてから採用する
            # （画像内の偽装テキスト・間接プロンプトインジェクション対策。
            # summary.py既存の_safe_attr設計思想をここでも踏襲する）。
            detected_name = _safe_attr(result.detected_name) or _safe_attr(
                result.detected_category_label
            )
        if condition is None and result.initial_condition != ItemCondition.UNKNOWN:
            condition = result.initial_condition
        for raw_value in (result.attributes.get("brand"), result.attributes.get("model_name")):
            value = _safe_attr(raw_value)
            if value and value not in notes and value != detected_name:
                notes.append(value)
        if result.initial_condition in _NOTABLE_CONDITIONS:
            notable = True

    if detected_name is None:
        return None, condition, None

    summary = detected_name
    if notes:
        summary = f"{summary}（{'、'.join(notes)}）"
    if notable:
        summary = f"{summary} 状態: 傷・使用感あり"
    if len(summary) > _MAX_ITEM_SUMMARY_LEN:
        summary = summary[:_MAX_ITEM_SUMMARY_LEN].rstrip() + "…"
    return detected_name, condition, summary


async def _analyze_items_with_budget(
    items: list[ItemAnalysisInput],
) -> list[ItemAnalysisResult]:
    """商品ごとのGemini呼び出しを、1案件あたり ``_MAX_GEMINI_CALLS_PER_CASE`` 回の
    予算内で Round1/Round2 に分けて実行する。

    Round1: 全商品に代表写真（1枚目）を割り当てる（商品数が予算以下なら全商品が
    必ず1回は解析される）。
    Round2: 残予算を sort_order 順（= items の並び順。呼び出し元でサーバ側の
    配列インデックスに正規化済み）に2枚目へ割り当てる。

    予算配分（＝実際に解析対象となる写真）が確定した後、``_run`` 内で初めて
    ``photo_url_for_ai`` を呼び出し base64 データURL化する（cases.py 側で
    全写真を先行してbase64化しない。security review 指摘対応）。
    """
    allocated: list[list[RawPhotoRef]] = [[] for _ in items]
    budget = _MAX_GEMINI_CALLS_PER_CASE

    for i, item in enumerate(items):
        if budget <= 0:
            break
        if item.photo_refs:
            allocated[i].append(item.photo_refs[0])
            budget -= 1

    for i, item in enumerate(items):
        if budget <= 0:
            break
        if len(item.photo_refs) >= 2:
            allocated[i].append(item.photo_refs[1])
            budget -= 1

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ITEM_ANALYSIS)

    async def _run(raw_refs: list[RawPhotoRef]) -> ItemAnalysisResult:
        if not raw_refs:
            return ItemAnalysisResult()
        async with semaphore:
            # 予算配分により実際に解析対象となった写真のみ、この時点で初めて
            # base64 データURL化する（storage.file_path 未存在・raw_url が
            # https でない等の理由で解決できない写真は None として除外する）。
            resolved: list[str] = []
            for storage_key, url in raw_refs:
                ref = await photo_url_for_ai(storage_key, url)
                if ref is not None:
                    resolved.append(ref)
            if not resolved:
                return ItemAnalysisResult()
            name, condition, item_summary = await analyze_item(photo_refs=resolved)
        return ItemAnalysisResult(
            ai_detected_name=name, ai_condition=condition, ai_summary=item_summary
        )

    # 1商品の解析タスクが例外を送出しても他商品・案件全体を巻き込まないよう
    # return_exceptions=True で個別に吸収する（analyze_item 自体は内部で
    # try/except済みだが、多層防御として維持する）。
    raw_results = await asyncio.gather(
        *(_run(refs) for refs in allocated), return_exceptions=True
    )

    results: list[ItemAnalysisResult] = []
    for raw in raw_results:
        if isinstance(raw, BaseException):
            logger.warning(
                "summary: 商品解析タスクが異常終了（当該商品はAI情報なしで継続）- %s: %s",
                type(raw).__name__,
                str(raw)[:200],
            )
            results.append(ItemAnalysisResult())
        else:
            results.append(raw)
    return results


async def generate_case_ai(
    *,
    purpose: str,
    housing_type: str | None,
    floor_plan: str | None,
    items: list[ItemAnalysisInput],
    ungrouped_refs: list[RawPhotoRef],
) -> tuple[str, list[ItemAnalysisResult]]:
    """商品ごとにグルーピングされた案件の Case.ai_summary と、各商品のAI解析結果を生成する。

    Returns:
        ``(case_ai_summary, item_results)``。``item_results`` は ``items`` と
        同じ並び順・同じ長さのリスト。

    Case.ai_summary のフォーマットは既存の ``generate_case_summary`` と同一
    （``f"{fallback} AI 検出品目: {ラベルを、で連結}。"``）。

    **「AI 検出品目」欄にはAIが実際に検出した結果（``ai_detected_name``）のみを
    使う。ユーザー入力の ``item.name`` は一切混ぜない**（security review 指摘
    対応: ユーザー入力を「AIが検出したかのように」表示するのは誤情報。
    ``item.name`` はユーザー入力名として ``CaseItemOut.name`` に別途そのまま
    表示され、ここでの集約対象ではない）。``ai_detected_name`` が None の
    商品は当該一覧から除外する（analyze_item 内部で detected_name/
    detected_category_label の順に既にフォールバック済みのため、ここでの
    3段目の「検出カテゴリ」フォールバックは実質 ai_detected_name に統合されている）。
    """
    item_results = await _analyze_items_with_budget(items)

    item_labels = [
        label for result in item_results if (label := result.ai_detected_name)
    ]
    # 未分類写真（商品グループに属さない写真）は generate_case_summary と同じ
    # 検出ロジック（_MAX_PHOTOS_FOR_AI 上限つき）で解析する。items側の予算とは
    # 独立した別枠（既存の未分類グループ用フォールバック機構をそのまま流用する）。
    # 実際に解析対象となる先頭 _MAX_PHOTOS_FOR_AI 枚のみ、この時点で初めて
    # base64 データURL化する（残りは一切base64化しない。security review指摘対応）。
    resolved_ungrouped_refs: list[str] = []
    for storage_key, url in ungrouped_refs[:_MAX_PHOTOS_FOR_AI]:
        ref = await photo_url_for_ai(storage_key, url)
        if ref is not None:
            resolved_ungrouped_refs.append(ref)
    ungrouped_labels = await _detect_photo_labels(resolved_ungrouped_refs, _MAX_PHOTOS_FOR_AI)

    all_labels = item_labels + ungrouped_labels
    total_photo_count = sum(len(item.photo_refs) for item in items) + len(ungrouped_refs)
    base = _fallback_summary(purpose, housing_type, floor_plan, total_photo_count)

    if not all_labels:
        return base, item_results
    labels_joined = "、".join(dict.fromkeys(all_labels))
    summary = f"{base} AI 検出品目: {labels_joined}。"
    if len(summary) > _MAX_SUMMARY_LEN:
        summary = summary[:_MAX_SUMMARY_LEN].rstrip() + "…"
    return summary, item_results
