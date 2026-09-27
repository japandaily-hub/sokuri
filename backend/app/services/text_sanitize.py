"""汎用テキスト無害化ユーティリティ — NFKC正規化・制御文字/Unicode双方向制御文字の除去、
表示用自由記述欄の拒否検証、保存不能文字（NUL・孤立サロゲート）の検出。

複数箇所（``services/summary.py`` の ``_safe_attr``、``schemas_katadzuke.py`` の
``CaseItemIn.name`` バリデータ等）で共通に必要となる「表示前の最低限の無害化」
処理をここに集約する（DRY。ロジックのズレ・改修漏れの防止）。

本モジュールは対象・扱いの異なる3つの方針を提供する（意図的に関数を分けている。
1つの関数へ統合すると「除去してよい欄」と「除去してはならない欄」が
呼び出し側の判断ミスで混線するため）:

① 除去（``normalize_and_strip_control_chars``。既存・不変）: NFKC正規化＋Unicode
   カテゴリ C*（制御・書式・私用領域・サロゲート・未割り当て）を全除去する。
   品名・口コミ・対応エリアなど、多少の除去で入力の意味が変わらない短い表示名向け。
② 拒否（``reject_disallowed_display_chars``）: 相手や公開画面に表示される自由記述欄
   （チャット本文・入札メッセージ・減額理由・自己紹介文等）向け。黙って除去すると
   入力者が書いた文章の一部が本人の知らないうちに変わってしまうため、対象文字を
   含む場合は保存前に 422 で突き返し、日本語で理由を伝える。
③ 拒否（``has_unsafe_storage_chars`` / ``replace_unsafe_storage_chars``）: 経路を問わず
   「そもそも保存できない文字」（NUL・孤立サロゲート）だけを検出する最小集合。
   PostgreSQL の text 列は NUL バイトを含む文字列を受け付けず
   （asyncpg ``CharacterNotInRepertoireError: invalid byte sequence for encoding
   "UTF8": 0x00``）、孤立サロゲートは UTF-8 へ符号化できない
   （``DataError: surrogates not allowed``）ため、個々のフィールドバリデータでは
   拾えない箇所（JSON のキー・クエリ文字列等）まで含めて落とす必要がある
   （``app.api.request_char_guard`` の全リクエスト共通防御から利用する）。
"""

from __future__ import annotations

import re
import unicodedata
from typing import overload


def strip_control_and_bidi_chars(text: str) -> str:
    """Unicode カテゴリ C*（制御文字・書式文字/Unicode双方向制御文字・
    私用領域・サロゲート・未割り当て）を全て除去する。

    表示崩れ・なりすまし（RLO/LRO 等の双方向制御文字による見た目偽装）対策。
    """
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")


def normalize_and_strip_control_chars(value: str) -> str:
    """NFKC正規化した上で制御文字・双方向制御文字を除去し、前後の空白を取り除く。"""
    text = unicodedata.normalize("NFKC", value).strip()
    return strip_control_and_bidi_chars(text).strip()


def _compile_char_class(ranges: tuple[tuple[int, int], ...]) -> re.Pattern[str]:
    """コードポイント範囲の一覧から「いずれかに該当すれば真」の文字クラス正規表現を組み立てる。

    ソースコードに ``\\u`` 形式のエスケープや不可視文字そのものを書かないため
    （エスケープが編集時の変換で本物の不可視文字に化けると、差分レビューで見えないまま
    ソースに混入する）、
    範囲の両端は必ず整数コードポイントから ``chr()`` で動的に生成し、``re.escape`` で
    正規表現の特殊文字（``\\``・``]``・``-`` 等）を無害化してから連結する。

    生成される正規表現は単純な文字クラス（``[...]``）1つのみで、バックトラックする
    量指定子や選択を含まないため、入力長 n に対して常に O(n) で判定できる
    （ReDoS の懸念がない）。
    """
    parts: list[str] = []
    for lo, hi in ranges:
        if lo == hi:
            parts.append(re.escape(chr(lo)))
        else:
            parts.append(f"{re.escape(chr(lo))}-{re.escape(chr(hi))}")
    return re.compile(f"[{''.join(parts)}]")


#: 表示用自由記述欄で拒否する文字（両端含むコードポイント範囲。昇順・重複なし）。
#: web/src/lib/text-guard.ts の DISALLOWED_DISPLAY_CHAR_RANGES と同じ集合にすること
#: （どちらか一方だけ更新すると、web が通した入力を backend が 422 で弾く／逆に
#: backend が拒否しない入力を web がサーバー未送信のまま加工してしまう食い違いが生まれる）。
#:
#: 根拠:
#: (1) 並べ替えによる見た目偽装の手段は Bidi_Control（UAX #9 双方向書式文字。
#:     Trojan Source 攻撃 CVE-2021-42574 が悪用した文字集合と同種）に限られる。
#:     改行 U+000A 以外の Cc は表示崩れ・ログ改行インジェクション・PG の NUL 500 の
#:     原因になり、孤立サロゲートは UTF-8 化できずいずれも 500 の原因になる。
#: (2) ZWJ（U+200D）・タグ文字・異体字セレクタ・ZWSP・BOM・ソフトハイフン・Co
#:     （私用領域）・Zl/Zp・Cn（未割り当て）は許可する。Cf を一括拒否すると
#:     家族絵文字（ZWJ 連結）やタグ旗（U+E0020–E007F）のような正当な合成が壊れる。
#:     Cn を拒否しないのは、実行環境の Python（unicodedata）が束ねる Unicode
#:     バージョンより新しく割り当てられた文字（新しい絵文字等）を誤って危険と
#:     判定してしまう偽陽性を避けるため（お問い合わせ ``_reject_non_newline_control_chars``
#:     の N-9 対応と同じ理由）。
#: (3) unicodedata を使わず固定のコードポイント範囲にする理由: (a) Bidi_Control は
#:     Unicode の属性だが Python の unicodedata モジュールはこれを公開していない。
#:     (b) unicodedata.unidata_version は Python のマイナーバージョン間でずれるため
#:     判定基準が実行環境依存になる。(c) Cc・Cs は Unicode の安定性方針
#:     （Stability Policy）で将来にわたり変わらない固定集合であるため、決め打ちで
#:     問題ない。(d) コンパイル済みの文字クラス正規表現（C実装）は1文字ずつ
#:     unicodedata.category() を呼ぶより高速。
#: (4) 判定は _compile_char_class が生成する単純な文字クラスのみ（バックトラック
#:     する量指定子や選択を含まない）のため、時間計算量は入力長に対し O(n)。
#: (5) 先行事例: Django の ``ProhibitNullCharactersValidator``（NUL 文字のみを対象に
#:     フォームフィールドを拒否する）[要確認: バージョン2.0で導入]。本実装は
#:     対象を Bidi_Control・NUL 以外の Cc・孤立サロゲートまで広げている。
#: (6) お問い合わせフォームの ``_reject_non_newline_control_chars``（Cc/Cf/Co/Cs を
#:     一括拒否）は、本関数より広い集合（Cf・Co も含む）を拒否する別方針として
#:     意図的に残す（Cf まで拒否するとチャット等の絵文字入り本文も 422 になるため
#:     基準が食い違うが、統合は別タスクとする）。
DISALLOWED_DISPLAY_CHAR_RANGES: tuple[tuple[int, int], ...] = (
    (0x0000, 0x0009),  # C0（NUL〜タブ）
    (0x000B, 0x001F),  # C0（改行 U+000A を除く。CR を含む）
    (0x007F, 0x009F),  # DEL・C1
    (0x061C, 0x061C),  # ALM（Arabic Letter Mark）
    (0x200E, 0x200F),  # LRM・RLM
    (0x202A, 0x202E),  # LRE・RLE・PDF・LRO・RLO
    (0x2066, 0x2069),  # LRI・RLI・FSI・PDI
    (0xD800, 0xDFFF),  # サロゲート（Python の str に単独で入るのは孤立したものだけ。
    # 正しいサロゲートペアは json.loads 等の時点で単一の補助面コードポイントに
    # 変換されているため、この範囲判定に達する前に消えている）。
)

#: すべての JSON 入力・クエリ文字列で拒否する「保存できない文字」の最小集合
#: （PostgreSQL の text 列は NUL を持てず、孤立サロゲートは UTF-8 化できない）。
#: DISALLOWED_DISPLAY_CHAR_RANGES の部分集合（NUL と孤立サロゲートのみ）であり、
#: フィールド単位の表示用バリデータが無い箇所（JSON のキー・クエリ文字列・
#: extra="forbid" モデルの未知フィールド名等）を経路を問わず一括で塞ぐために使う。
UNSAFE_STORAGE_CHAR_RANGES: tuple[tuple[int, int], ...] = (
    (0x0000, 0x0000),
    (0xD800, 0xDFFF),
)

_DISALLOWED_DISPLAY_CHARS_RE = _compile_char_class(DISALLOWED_DISPLAY_CHAR_RANGES)
_UNSAFE_STORAGE_CHARS_RE = _compile_char_class(UNSAFE_STORAGE_CHAR_RANGES)


def has_disallowed_display_chars(text: str) -> bool:
    """表示用自由記述欄で拒否すべき文字（DISALLOWED_DISPLAY_CHAR_RANGES）を1文字でも含むか判定する。"""
    return _DISALLOWED_DISPLAY_CHARS_RE.search(text) is not None


@overload
def reject_disallowed_display_chars(value: str, *, field_label: str) -> str: ...
@overload
def reject_disallowed_display_chars(value: None, *, field_label: str) -> None: ...


def reject_disallowed_display_chars(value: str | None, *, field_label: str) -> str | None:
    """表示用自由記述欄の field validator 本体。

    ``None`` はそのまま ``None`` を返す（Optional 欄で値が省略・null 送信された場合、
    ここでは何もしない。省略時にバリデータ自体が呼ばれない Pydantic の挙動と合わせ、
    ``BidUpdateRequest`` 等の「省略＝現状維持」セマンティクスを壊さない）。
    ``DISALLOWED_DISPLAY_CHAR_RANGES`` に該当する文字を1つでも含む場合は
    ``ValueError(f"{field_label}に制御文字を含めることはできません。")`` を投げる
    （``normalize_and_strip_control_chars`` と異なり、値を書き換えずに拒否する。
    入力者の書いた文章を黙って変えないため）。該当しなければ ``value`` をそのまま返す。
    """
    if value is None:
        return None
    if has_disallowed_display_chars(value):
        raise ValueError(f"{field_label}に制御文字を含めることはできません。")
    return value


def has_unsafe_storage_chars(text: str) -> bool:
    """NUL・孤立サロゲート（UNSAFE_STORAGE_CHAR_RANGES）を1文字でも含むか判定する。"""
    return _UNSAFE_STORAGE_CHARS_RE.search(text) is not None


def replace_unsafe_storage_chars(text: str) -> str:
    """NUL・孤立サロゲートを置換文字 U+FFFD に置き換える（値そのものではなく
    ログ・エラー応答の ``loc`` に載せる文字列を安全化するための用途限定関数）。

    置換後の文字列は UNSAFE_STORAGE_CHAR_RANGES を含まないため、ログ出力や
    JSON 応答へそのまま書き込んでも 500（保存できない文字によるエンコード失敗）
    を誘発しない。
    """
    return _UNSAFE_STORAGE_CHARS_RE.sub(chr(0xFFFD), text)
