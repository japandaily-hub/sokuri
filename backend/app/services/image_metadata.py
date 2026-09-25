"""画像メタデータ除去 — EXIF・XMP・IPTC 等を、画素データを再エンコードせずに取り除く。

security review 確定指摘（MEDIUM・独立検証 TRUE_POSITIVE 8/10）対応。案件写真を EXIF
付きのまま保存・配信していたため、承認済み業者（active/limited）が成約前に依頼者の
自宅の GPS 座標を写真から取得できた（「住所は成約まで非開示」の約束を実質的に破る）。
受信（``PUT /upload/{key}``）と配信（``GET /files/{key}``）の両方で
:func:`strip_image_metadata` を通す。配信時にも通すのは、対策以前に保存された写真を
本番データの書き換えなしで即時に塞ぐため（R2 は ``IfNoneMatch="*"`` で上書き不可・
ETag=storage_key のため、既存オブジェクトを差し替える移行はしない）。

設計方針:

- ロスレス: 画素データ（JPEG のエントロピー符号データ・PNG の IDAT・WebP のビット
  ストリーム）はバイト単位でそのまま残す。画質が劣化せず、配信のたびに通しても数 ms で
  済む。画像ライブラリには依存しない（依存追加なし・保守終了の piexif も使わない）。
- 許可リスト方式: 「既知のメタデータを消す」のではなく「表示に必要と分かっているもの
  だけを残す」。C2PA（JPEG の APP11・PNG の caBX）・旧仕様の PNG ``exIf``・アプリ独自の
  チャンク・JPEG の EOI 以降に連結された副画像や Motion Photo の動画も一緒に落ちる。
- 向き: Exif のうち表示に影響する Orientation（2〜8）だけは、JPEG の APP1・PNG の eXIf・
  WebP の EXIF とも、Orientation 1 個だけを持つ最小の Exif に作り直して元の位置に残す
  （GPS 等の他のタグは一切残さない）。
- fail closed: 構造を解釈できない入力は :class:`ImageMetadataError` とし、元のバイト列は
  決して返さない。呼び出し元も元のバイト列へフォールバックしてはならない。
- JPEG の軽微な破損は libjpeg（Chrome / Firefox のデコーダ）と同じ範囲で受け付ける
  （QA 指摘 M1: 警告付きで表示できる写真まで拒否すると、既存の保存写真が業者に見えなく
  なる）。EOI の欠落は EOI を補い、セグメント間の余分なバイト・0xFF00・長さを短く申告
  した APPn は次のマーカーまで読み飛ばす。読み飛ばしたバイトは出力しない。その代わり、
  残すセグメントは中身の構造と長さを突き合わせ（本来の長さへの切り詰め・不整合は例外）、
  長さを偽ったセグメントが後続の Exif 等を飲み込んだまま複製されないようにする。
- 計算量: 入力長 n に対して O(n)。セグメント・チャンク数・再同期に上限を設け、細工された
  入力で 1 リクエストあたりの CPU 時間が膨らむのを防ぐ（配信は無認証の capability URL の
  ため、保存済みの細工ファイルを繰り返し取得されても重くならないようにする）。
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass

__all__ = ["IMAGE_MIME_TYPES", "ImageMetadataError", "strip_image_metadata"]

# ``storage.sniff_image_ext`` の戻り値（実バイトから判定した形式）→ MIME。AI 解析（Gemini）へ
# 送るデータ URL の型は、保存時の content_type や利用者の申告ではなくこれで決める。
IMAGE_MIME_TYPES: dict[str, str] = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class ImageMetadataError(Exception):
    """画像の構造を解釈できず、メタデータの除去を保証できないことを示す例外。

    呼び出し元は元のバイト列へフォールバックしてはならない（fail closed。アップロードは
    415、配信は 404 に翻訳する）。メッセージは構造上の理由だけで構成し、画像のバイト列
    そのものは含めない（そのままログに出してよい）。
    """


def strip_image_metadata(data: bytes, ext: str) -> bytes:
    """画像からメタデータを取り除いたバイト列を返す（画素データは再エンコードしない）。

    Args:
        data: 画像のバイト列（サイズ上限は呼び出し元の MAX_UPLOAD_BYTES=10MB）。
        ext: 画像形式。``storage.sniff_image_ext`` の戻り値（``"jpeg"`` | ``"png"`` |
            ``"webp"``）を渡す。storage_key の拡張子表記（``"jpg"``）も受け付ける。

    Returns:
        メタデータを除いた画像のバイト列。同じ入力に対して常に同じ出力になり、出力を
        再度通しても変わらない（冪等）。配信時に毎回通しても ETag（= storage_key）が
        指す表現が変わらないことの前提になる。

    Raises:
        ImageMetadataError: 対応外の形式、または構造を解釈できない入力。
    """
    normalized_ext = ext.lower()
    if normalized_ext in ("jpeg", "jpg"):
        return _strip_jpeg(data)
    if normalized_ext == "png":
        return _strip_png(data)
    if normalized_ext == "webp":
        return _strip_webp(data)
    raise ImageMetadataError(f"未対応の画像形式です: {ext!r}")


# ──────────────────────────── JPEG ────────────────────────────

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"

_MARKER_TEM = 0x01
_MARKER_DHT = 0xC4
_MARKER_DAC = 0xCC
_MARKER_EOI = 0xD9
_MARKER_SOS = 0xDA
_MARKER_DQT = 0xDB
_MARKER_DNL = 0xDC
_MARKER_DRI = 0xDD
_MARKER_EXP = 0xDF
_MARKER_APP0 = 0xE0
_MARKER_APP1 = 0xE1
_MARKER_APP2 = 0xE2
_MARKER_APP14 = 0xEE
_MARKER_COM = 0xFE
_RST_MARKERS = range(0xD0, 0xD8)
_APP_MARKERS = range(0xE0, 0xF0)

# SOF0〜SOF15（0xC4=DHT・0xC8=JPG（予約）・0xCC=DAC を除く）と、同じ構造の DHP。
_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
_MARKER_DHP = 0xDE
_FRAME_HEADER_MARKERS = _SOF_MARKERS | {_MARKER_DHP}
# 画素の復元に使う長さ付きセグメント（構造を検証したうえでそのまま残す）。SOS は直後の
# エントロピー符号データと合わせて、DNL は長さが正しいときだけ残すため別に扱う。
_IMAGE_STRUCTURE_MARKERS = _FRAME_HEADER_MARKERS | {
    _MARKER_DHT, _MARKER_DAC, _MARKER_DQT, _MARKER_DRI, _MARKER_EXP,
}  # fmt: skip

# APPn のうち残すのは APP0 JFIF・APP2 ICC_PROFILE・APP14 Adobe だけで、識別子が一致しない
# 同番号のセグメント（JFXX サムネイル・MPF・FlashPix 等）と、それ以外の APPn（APP1 の
# Exif / XMP / 拡張 XMP・APP11 の JUMBF / C2PA・APP13 の Photoshop / IPTC 等）・COM は
# すべて落とす。残す 3 種は、長さを偽って後続のセグメントを飲み込んだまま複製しないよう
# 本来の長さ（JFIF・Adobe は固定部＋サムネイル、ICC はプロファイル自身の申告長）に揃える。
_JFIF_IDENTIFIER = b"JFIF\x00"
_JFIF_FIXED_SIZE = 14  # 識別子 5・版 2・単位 1・画素密度 4・サムネイル寸法 2（続けて RGB 画素）
_ICC_IDENTIFIER = b"ICC_PROFILE\x00"
_ICC_CHUNK_OVERHEAD = len(_ICC_IDENTIFIER) + 2  # 識別子・通し番号・総数
_ICC_HEADER_SIZE = 128  # ICC プロファイルのヘッダ長（先頭 4 バイトがプロファイル全体の長さ）
_ADOBE_IDENTIFIER = b"Adobe"
_ADOBE_SIZE = 12  # 識別子 5・版 2・フラグ 4・色変換 1

# 向きの引き継ぎに使う Exif / TIFF の定数（CIPA DC-008 / TIFF 6.0）。
# 識別子の 6 バイト目はパディング（通常 0x00）で、Chromium と同じく値は問わない。
_EXIF_IDENTIFIER = b"Exif\x00"
_EXIF_HEADER_SIZE = 6
_TIFF_HEADER_SIZE = 8
_TIFF_MAGIC = 42
_TIFF_TYPE_SHORT = 3
_TAG_ORIENTATION = 0x0112
_IFD_ENTRY_SIZE = 12
# 1（正立）以外の有効値。1 と範囲外の値は Exif ごと捨てる（表示は正立のまま変わらない）。
_ROTATED_ORIENTATIONS = range(2, 9)

# 1 ファイルあたりの上限。実際の写真はセグメント数十（ICC の分割・拡張 XMP・プログレッシブの
# スキャンを含めても数百）、表は数十に収まる。細工された入力で Python レベルのループが
# 数十万回回るのを防ぐ。
_MAX_JPEG_SEGMENTS = 10_000
_MAX_JPEG_TABLES = 1_024  # 量子化表・ハフマン表・算術符号の条件の合計
# 再同期（マーカーが期待位置に無いときの読み飛ばし）の上限。1 回あたりはセグメント 1 個分。
_MAX_RESYNC_BYTES = 64 * 1024
_MAX_JPEG_RESYNCS = 256
# 向き（Orientation）を探す範囲の上限。実際の写真の Exif APP1 は 1 個、IFD0 のエントリは
# 数十件に収まる。エントリ数 0xFFFF の APP1 を大量に並べた細工入力で、無認証の配信経路の
# Python ループが数十万回回るのを防ぐ（読む範囲を絞るだけで、APP1 自体は従来どおり全部落とす）。
_MAX_EXIF_ORIENTATION_PROBES = 4
_MAX_IFD0_ENTRIES = 1_024

# エントロピー符号データの走査窓。1 回の正規表現探索で GIL を握る時間を数 ms に抑え、
# 巨大な入力でもイベントループ（別スレッド）を長く止めない。
_ENTROPY_SCAN_WINDOW = 256 * 1024

# マーカー直前のフィルバイト（0xFF の連続）。
_FILL_BYTES_RE = re.compile(rb"\xff+")
# エントロピー符号データ中の「本物のマーカー」: 0xFF の直後が 0x00（スタッフィング）・
# 0xD0〜0xD7（RST）・0xFF（フィル）のいずれでもないもの。
_ENTROPY_MARKER_RE = re.compile(rb"\xff[^\x00\xd0-\xd7\xff]")
# 再同期先: 0xFF の直後が 0x00 でも 0xFF でもない位置（libjpeg の next_marker と同じ判定）。
_RESYNC_MARKER_RE = re.compile(rb"\xff[^\x00\xff]")
# 残すデータ（スキャンデータ・残すセグメントの中身）に紛れ込んだメタデータの目印。壊れた
# ファイルでは、マーカー（EOI や後続の APP1）が欠けると後ろの Exif / XMP がエントロピー符号
# データとして吸収され、残すセグメントの中身が削られると長さは整合したまま後続のセグメントが
# 飲み込まれる。飲み込みは必ず後続セグメントの先頭から始まるため、GPS の値まで届くなら Exif
# （と MPF）は TIFF ヘッダを、XMP は Adobe の名前空間を必ず含む。IFD0 のオフセットが 8 以外の
# Exif や、市区町村名等を持つ IPTC を丸ごと飲み込んだ場合に備え、Exif と Photoshop（IPTC）の
# 識別子も目印に加える（security review Low）。いずれも 6 バイト以上で、画素データや
# ICC プロファイルと偶然一致する確率は無視できる（10MB あたり 1e-7 未満）。
_METADATA_SIGNATURES = (
    b"II*\x00\x08\x00\x00\x00",  # TIFF ヘッダ（リトルエンディアン・IFD0 がオフセット 8）
    b"MM\x00*\x00\x00\x00\x08",  # 同（ビッグエンディアン）
    b"http://ns.adobe.com/",  # XMP（exif:GPSLatitude 等の名前空間）
    b"Exif\x00\x00",  # Exif APP1 の識別子（IFD0 のオフセットを問わない）
    b"Photoshop 3.0\x00",  # APP13（IPTC）の識別子
)


@dataclass(frozen=True, slots=True)
class _IccChunk:
    """出力に仮置きした ICC プロファイルの分割チャンク（最後にまとめて整合を確かめる）。"""

    output_index: int
    marker_start: int
    payload_start: int
    segment_end: int
    sequence: int
    count: int

    @property
    def data_start(self) -> int:
        """プロファイル本体（識別子・通し番号・総数の後ろ）の開始位置。"""
        return self.payload_start + _ICC_CHUNK_OVERHEAD


def _strip_jpeg(data: bytes) -> bytes:
    """JPEG をセグメント単位で走査し、画素の復元に必要なものだけをつなぎ直す。

    - 残す: SOI・APP0 JFIF・APP2 ICC_PROFILE・APP14 Adobe・DQT / DHT / SOFn / DRI / SOS 等と
      エントロピー符号データ（バイト単位で同一）・EOI。残すセグメントは
      :func:`_validate_image_segment` 等で中身の構造と長さを突き合わせる。
    - 落とす: 上記以外の APPn（Exif / XMP / IPTC / MPF / C2PA 等）・COM・EOI 以降の全データ
      （MPF の副画像・Motion Photo の動画等。別の Exif / GPS を含むため）・セグメント間の
      フィルバイトと単独マーカー（RST / TEM）・再同期で読み飛ばしたバイト。
    - 向き: 最初に Orientation を読めた Exif APP1 の位置に、Orientation だけを持つ最小の
      Exif APP1 を置き直す（値が 2〜8 のときのみ。:func:`_read_exif_orientation`）。
    - 途中切れ: 最初の SOS ヘッダを読み終えた後なら、途切れた不完全な部分を捨てて EOI を
      補う。それより前で途切れたもの・SOS より前に EOI があるもの（画像データが無い）は例外。
    - 壊れたファイルへの備え: 正しいファイルのスキャンデータにメタデータは入らないが、マーカー
      が欠けると後続の Exif / XMP がスキャンデータとして吸収され得る。SOS ヘッダ・スキャン
      データと残すセグメントの中身に Exif（TIFF ヘッダ）・XMP の目印があれば例外（ICC だけは
      通し番号順につないだプロファイル全体で探し、あれば ICC を全部落とす）、SOF の重複・SOF
      より前の SOS（libjpeg も致命エラー）も例外。ICC・サムネイル付き JFIF を残した後、次に
      残すセグメントまでの間（捨てるセグメントを挟んでもよい）に再同期が起きたら、中身が
      削られて後続を飲み込んだ疑いがあるため ICC は全部・JFIF はサムネイルを落とす。
    """
    if not data.startswith(_JPEG_SOI):
        raise ImageMetadataError("JPEG: 先頭に SOI マーカーがありません")
    total = len(data)
    view = memoryview(data)
    output: list[bytes | memoryview] = [_JPEG_SOI]
    icc_chunks: list[_IccChunk] = []
    icc_tainted = False
    # 直前に残した「中身を構造で確かめられない」セグメント（ICC・サムネイル付き JFIF）。
    # 次に残すセグメントを処理するまでの間に再同期が起きたら、長さと中身が食い違っている
    # （中身が削られて後続のセグメントの先頭を飲み込んだ等）とみなし、ICC は全部落とし、JFIF
    # はサムネイルを落とす。間に捨てるセグメント（APPn・COM・TEM・RST 等）を挟んでも持ち越す
    # （飲み込んだ残りが偶然マーカーの形をしていると、再同期はその捨てるセグメントの後ろで
    # 起きるため）。残すセグメントを処理した時点で解消する（下の各分岐で設定し直す）。
    icc_just_kept = False
    jfif_thumbnail_just_kept: tuple[int, int, int] | None = None
    orientation_decided = False
    orientation_probes = 0
    frame_started = False
    scan_started = False
    resync_count = 0
    table_count = 0
    pos = len(_JPEG_SOI)
    for _ in range(_MAX_JPEG_SEGMENTS):
        located = _locate_next_marker(data, pos)
        if located is None:
            return _finish_jpeg(
                output, data, icc_chunks, icc_tainted, truncated=True, scan_started=scan_started
            )
        marker_start, skipped_bytes = located
        if skipped_bytes:
            resync_count += 1
            if resync_count > _MAX_JPEG_RESYNCS:
                raise ImageMetadataError(
                    f"JPEG: マーカーの再同期が上限（{_MAX_JPEG_RESYNCS} 回）を超えています"
                )
            icc_tainted = icc_tainted or icc_just_kept
            if jfif_thumbnail_just_kept is not None:
                output_index, jfif_start, jfif_end = jfif_thumbnail_just_kept
                output[output_index] = _trimmed_segment(
                    view, jfif_start, jfif_end, _JFIF_FIXED_SIZE
                )
            icc_just_kept, jfif_thumbnail_just_kept = False, None
        code_pos = marker_start + 1
        marker = data[code_pos]

        if marker == _MARKER_EOI:
            if not scan_started:
                raise ImageMetadataError("JPEG: 画像データ（SOS）の前に EOI があります")
            return _finish_jpeg(
                output, data, icc_chunks, icc_tainted, truncated=False, scan_started=True
            )
        if marker == _MARKER_TEM or marker in _RST_MARKERS:
            # セグメントの切れ目に現れたパラメータ無しのマーカーは意味を持たないため捨てる。
            pos = code_pos + 1
            continue
        droppable = marker in _APP_MARKERS or marker == _MARKER_COM
        if not (
            droppable
            or marker == _MARKER_SOS
            or marker == _MARKER_DNL
            or marker in _IMAGE_STRUCTURE_MARKERS
        ):
            # SOI の再出現・予約マーカー（0x02〜0xBF・JPG=0xC8・JPGn=0xF0〜0xFD）。libjpeg
            # （ブラウザの JPEG デコーダ）も致命エラーにする種類で、長さの解釈も保証できない。
            raise ImageMetadataError(f"JPEG: 解釈できないマーカー 0xFF{marker:02X} です")

        if code_pos + 3 > total:
            return _finish_jpeg(
                output, data, icc_chunks, icc_tainted, truncated=True, scan_started=scan_started
            )
        (length,) = struct.unpack_from(">H", data, code_pos + 1)
        payload_start = code_pos + 3
        if length < 2:
            if not droppable:
                raise ImageMetadataError("JPEG: セグメント長が不正です")
            # libjpeg と同じく長さ 0 とみなし、長さ欄の直後から次のマーカーを探す。
            pos = payload_start
            continue
        segment_end = code_pos + 1 + length
        if segment_end > total:
            return _finish_jpeg(
                output, data, icc_chunks, icc_tainted, truncated=True, scan_started=scan_started
            )

        if marker == _MARKER_SOS:
            if not frame_started:
                raise ImageMetadataError("JPEG: SOF より前に SOS があります")
            _validate_scan_header(data[payload_start:segment_end])
            scan_started = True
            # SOS ヘッダと直後のエントロピー符号データ（RST・スタッフィングを含む）を
            # 次のマーカーの直前まで一括で残す。目印は残す範囲全体（SOS ヘッダの中身から）で
            # 探し、ヘッダの中身・ヘッダとスキャンデータの境目をまたぐものも見逃さない。
            scan_end = _find_entropy_marker(data, segment_end)
            if _contains_metadata_signature(data, payload_start, scan_end):
                raise ImageMetadataError(
                    "JPEG: 画像データの中に Exif / XMP の断片があります（マーカーの欠落）"
                )
            icc_just_kept, jfif_thumbnail_just_kept = False, None
            output.append(view[marker_start:scan_end])
            if scan_end >= total:
                # EOI が無いまま終わっている（途中切れ）。EOI を補って終える。
                return _finish_jpeg(
                    output, data, icc_chunks, icc_tainted, truncated=True, scan_started=True
                )
            pos = scan_end
            continue
        if marker in _SOF_MARKERS:
            # libjpeg と同じく 2 個目の SOF は致命エラー（EOI が欠けて後ろに連結された副画像まで
            # 読み進んだ場合も、ここで止まる）。
            if frame_started:
                raise ImageMetadataError("JPEG: SOF が 2 個あります")
            frame_started = True
        if marker in _IMAGE_STRUCTURE_MARKERS:
            table_count += _validate_image_segment(
                marker, data[payload_start:segment_end], _MAX_JPEG_TABLES - table_count
            )
            if _contains_metadata_signature(data, payload_start, segment_end):
                raise ImageMetadataError(
                    f"JPEG: マーカー 0xFF{marker:02X} の中に Exif / XMP の断片があります"
                )
            icc_just_kept, jfif_thumbnail_just_kept = False, None
            output.append(view[marker_start:segment_end])
        elif marker == _MARKER_DNL:
            # 行数（2 バイト）だけを持つ。長さが違うものは libjpeg も読み飛ばすだけなので落とす。
            if length == 4:
                icc_just_kept, jfif_thumbnail_just_kept = False, None
                output.append(view[marker_start:segment_end])
        elif marker == _MARKER_APP1:
            # Exif / XMP / 拡張 XMP はすべて落とす。向きだけは表示に影響するため引き継ぐ
            # （作り直した最小の Exif は元の APP1 を残したものではないため、直前に残した ICC・
            # JFIF の疑いは解消しない）。
            if not orientation_decided and orientation_probes < _MAX_EXIF_ORIENTATION_PROBES:
                orientation_probes += 1
                found = _read_exif_orientation(data[payload_start:segment_end])
                if found is not None:
                    orientation_decided = True
                    orientation, endian = found
                    if orientation in _ROTATED_ORIENTATIONS:
                        output.append(_build_orientation_only_exif(orientation, endian))
        elif marker == _MARKER_APP0:
            if data.startswith(_JFIF_IDENTIFIER, payload_start, segment_end):
                kept_size = _jfif_payload_size(data, payload_start, segment_end)
                if _contains_metadata_signature(data, payload_start, payload_start + kept_size):
                    raise ImageMetadataError("JPEG: JFIF の中に Exif / XMP の断片があります")
                icc_just_kept = False
                jfif_thumbnail_just_kept = (
                    (len(output), marker_start, segment_end)
                    if kept_size > _JFIF_FIXED_SIZE
                    else None
                )
                output.append(_trimmed_segment(view, marker_start, segment_end, kept_size))
        elif marker == _MARKER_APP2:
            if segment_end - payload_start > _ICC_CHUNK_OVERHEAD and data.startswith(
                _ICC_IDENTIFIER, payload_start, segment_end
            ):
                # 分割チャンクがそろって初めて整合を確かめられるため、仮置きして最後に確定する。
                icc_chunks.append(
                    _IccChunk(
                        output_index=len(output),
                        marker_start=marker_start,
                        payload_start=payload_start,
                        segment_end=segment_end,
                        sequence=data[payload_start + len(_ICC_IDENTIFIER)],
                        count=data[payload_start + len(_ICC_IDENTIFIER) + 1],
                    )
                )
                icc_just_kept, jfif_thumbnail_just_kept = True, None
                output.append(view[marker_start:segment_end])
        elif marker == _MARKER_APP14:
            if data.startswith(_ADOBE_IDENTIFIER, payload_start, segment_end):
                kept_size = min(segment_end - payload_start, _ADOBE_SIZE)
                icc_just_kept, jfif_thumbnail_just_kept = False, None
                output.append(_trimmed_segment(view, marker_start, segment_end, kept_size))
        # それ以外の APPn・COM は落とす。
        pos = segment_end
    raise ImageMetadataError(f"JPEG: セグメント数が上限（{_MAX_JPEG_SEGMENTS}）を超えています")


def _locate_next_marker(data: bytes, pos: int) -> tuple[int, int] | None:
    """セグメントの切れ目 ``pos`` から次のマーカーを探す。

    戻り値は ``(マーカー直前の 0xFF の位置, 読み飛ばしたバイト数)``。通常はフィルバイト
    （0xFF の連続）の直後に 0x00 以外のマーカーコードが来る（読み飛ばし 0）。来ない場合は
    libjpeg の next_marker と同じく、「0xFF の直後が 0x00 でも 0xFF でもない位置」まで
    読み飛ばして再同期する（セグメント間の余分なバイト・0xFF00・長さを短く申告した APPn の
    残り等）。読み飛ばしたバイトは呼び出し元で出力しない。マーカーを見つける前にデータが
    終わった場合は ``None``。

    Raises:
        ImageMetadataError: 読み飛ばしが :data:`_MAX_RESYNC_BYTES` を超える。
    """
    total = len(data)
    fill = _FILL_BYTES_RE.match(data, pos)
    if fill is not None:
        code_pos = fill.end()
        if code_pos >= total:
            return None
        if data[code_pos] != 0x00:
            return code_pos - 1, 0
    window_end = min(pos + _MAX_RESYNC_BYTES + 2, total)
    found = _RESYNC_MARKER_RE.search(data, pos, window_end)
    if found is not None:
        return found.start(), found.start() - pos
    if window_end >= total:
        return None
    raise ImageMetadataError(
        f"JPEG: マーカーを再同期できません（{_MAX_RESYNC_BYTES} バイトを超える読み飛ばし）"
    )


def _finish_jpeg(
    output: list[bytes | memoryview],
    data: bytes,
    icc_chunks: list[_IccChunk],
    icc_tainted: bool,
    *,
    truncated: bool,
    scan_started: bool,
) -> bytes:
    """ICC の分割チャンクを確定し、EOI で閉じた出力を返す。

    ``truncated``（EOI に達する前にデータが終わった）の場合、最初の SOS ヘッダを読み終えて
    いれば、途切れた不完全な部分は出力に含めずに EOI を補う（libjpeg も終端に擬似 EOI を
    補って表示する）。読み終えていなければ画像データが無いため例外。
    """
    if truncated and not scan_started:
        raise ImageMetadataError("JPEG: 画像データ（SOS）に達する前にデータが途切れています")
    _settle_icc_chunks(output, data, icc_chunks, icc_tainted)
    output.append(_JPEG_EOI)
    return b"".join(output)


def _contains_metadata_signature(data: bytes, start: int, end: int) -> bool:
    """``data[start:end]`` に Exif（TIFF ヘッダ）・XMP の目印が含まれるか（C 実装の find）。"""
    return any(data.find(signature, start, end) != -1 for signature in _METADATA_SIGNATURES)


def _trimmed_segment(
    view: memoryview, marker_start: int, segment_end: int, payload_size: int
) -> bytes | memoryview:
    """セグメントをペイロード ``payload_size`` バイトまでに切り詰めて返す（不要ならそのまま）。"""
    payload_start = marker_start + 4
    if payload_start + payload_size >= segment_end:
        return view[marker_start:segment_end]
    header = bytes((0xFF, view[marker_start + 1])) + struct.pack(">H", payload_size + 2)
    return header + view[payload_start : payload_start + payload_size]


def _jfif_payload_size(data: bytes, payload_start: int, segment_end: int) -> int:
    """APP0 JFIF の本来のペイロード長（固定部 14 バイト＋ RGB サムネイル）を返す。"""
    declared_size = segment_end - payload_start
    if declared_size < _JFIF_FIXED_SIZE:
        return declared_size
    thumbnail_size = 3 * data[payload_start + 12] * data[payload_start + 13]
    return min(declared_size, _JFIF_FIXED_SIZE + thumbnail_size)


def _settle_icc_chunks(
    output: list[bytes | memoryview], data: bytes, chunks: list[_IccChunk], tainted: bool
) -> None:
    """仮置きした ICC の分割チャンクを、整合が取れる場合だけ残す（出力をその場で書き換える）。

    通し番号が 1〜総数でそろい、合計長がプロファイル自身の申告長（本体先頭 4 バイト）と一致
    すれば残す。1 チャンクで申告長より長い場合は、長さを偽ったチャンクが後続のセグメント
    （Exif 等）を飲み込んでいる可能性があるため申告長に切り詰める。それ以外（欠落・重複・
    複数チャンクでの長さ不一致・壊れたヘッダ）と、中身が削られて後続のセグメントを飲み込んだ
    疑いがある場合（``tainted``: いずれかのチャンクを残した後、次に残すセグメントまでに再同期が
    起きた／残すプロファイルに Exif・XMP の目印がある）は全部落とす。目印は、デコーダ
    （libjpeg-turbo の jpeg_read_icc_profile）が組み立てるのと同じく通し番号順につないだ
    プロファイル全体で 1 回だけ探す（チャンクの境目をまたぐ目印も見逃さない）。Chromium
    （jpeg_read_icc_profile と skcms）も前者の ICC は使わないため表示は変わらず、後者も色が
    sRGB 扱いになるだけで写真自体は配信できる。
    """
    if not chunks:
        return
    if tainted:
        for chunk in chunks:
            output[chunk.output_index] = b""
        return
    view = memoryview(data)
    count = chunks[0].count
    sequences = sorted(chunk.sequence for chunk in chunks)
    if all(chunk.count == count for chunk in chunks) and sequences == list(range(1, count + 1)):
        first = next(chunk for chunk in chunks if chunk.sequence == 1)
        if first.segment_end - first.data_start >= 4:
            (profile_size,) = struct.unpack_from(">I", data, first.data_start)
            stored_size = sum(chunk.segment_end - chunk.data_start for chunk in chunks)
            if profile_size >= _ICC_HEADER_SIZE:
                if stored_size == profile_size:
                    profile = b"".join(
                        view[chunk.data_start : chunk.segment_end]
                        for chunk in sorted(chunks, key=lambda chunk: chunk.sequence)
                    )
                    if not _contains_metadata_signature(profile, 0, len(profile)):
                        return
                elif count == 1 and stored_size > profile_size:
                    profile_end = first.data_start + profile_size
                    if not _contains_metadata_signature(data, first.data_start, profile_end):
                        output[first.output_index] = _trimmed_segment(
                            view,
                            first.marker_start,
                            first.segment_end,
                            _ICC_CHUNK_OVERHEAD + profile_size,
                        )
                        return
    for chunk in chunks:
        output[chunk.output_index] = b""


def _validate_scan_header(payload: bytes) -> None:
    """SOS ヘッダの長さを成分数と突き合わせる（libjpeg と同じ規則: 成分 1〜4・長さ 4+2n）。"""
    component_count = payload[0] if payload else 0
    if not 1 <= component_count <= 4 or len(payload) != 4 + 2 * component_count:
        raise ImageMetadataError("JPEG: SOS の長さが構造と整合しません")


def _validate_image_segment(marker: int, payload: bytes, table_limit: int) -> int:
    """画素の復元に使うセグメントの長さを、中身の構造と突き合わせる。

    長さを実際より長く偽ったセグメントが後続のセグメント（Exif 等）を飲み込んだまま出力へ
    複製されるのを防ぐ。飲み込んだ部分は後続セグメントの 0xFF から始まるため、表の見出しや
    固定長の検査で必ず不整合になる。規則は libjpeg（ブラウザ）と同じか、それより少し厳しい
    程度で、libjpeg も長さ不整合は致命エラーにするため表示できる写真を拒むことにはならない。

    Returns:
        消費した表の数（量子化表・ハフマン表・算術符号の条件）。

    Raises:
        ImageMetadataError: 構造と長さが整合しない、または表の数が ``table_limit`` を超える。
    """
    size = len(payload)
    if marker == _MARKER_DQT:
        return _count_quantization_tables(payload, table_limit)
    if marker == _MARKER_DHT:
        return _count_huffman_tables(payload, table_limit)
    if marker == _MARKER_DAC:
        conditions = size // 2
        if size % 2 or conditions > table_limit or (size and max(payload[0::2]) >= 32):
            raise ImageMetadataError("JPEG: DAC の長さ・表番号が不正です")
        return conditions
    if marker == _MARKER_DRI:
        valid = size == 2
    elif marker == _MARKER_EXP:
        valid = size == 1
    else:  # SOFn・DHP: 固定 6 バイト＋成分ごとに 3 バイト
        valid = size >= 6 and size == 6 + 3 * payload[5]
    if not valid:
        raise ImageMetadataError(f"JPEG: マーカー 0xFF{marker:02X} の長さが構造と整合しません")
    return 0


def _count_quantization_tables(payload: bytes, table_limit: int) -> int:
    """DQT の量子化表を数える（精度 0/1・表番号 0〜3・表の長さちょうどでなければ例外）。"""
    size = len(payload)
    index = tables = 0
    while index < size:
        precision, table_id = payload[index] >> 4, payload[index] & 0x0F
        if precision > 1 or table_id > 3:
            raise ImageMetadataError("JPEG: DQT の表の見出しが不正です")
        index += 1 + 64 * (precision + 1)
        tables += 1
        if tables > table_limit:
            raise ImageMetadataError(f"JPEG: 表の数が上限（{_MAX_JPEG_TABLES}）を超えています")
    if index != size:
        raise ImageMetadataError("JPEG: DQT の長さが表の構造と整合しません")
    return tables


def _count_huffman_tables(payload: bytes, table_limit: int) -> int:
    """DHT のハフマン表を libjpeg（jdmarker.c get_dht）と同じ規則で数える（不整合は例外）。"""
    size = len(payload)
    index = tables = 0
    while size - index > 16:
        table_class, table_id = payload[index] >> 4, payload[index] & 0x0F
        if table_class > 1 or table_id > 3:
            raise ImageMetadataError("JPEG: DHT の表の見出しが不正です")
        symbol_count = sum(payload[index + 1 : index + 17])
        index += 17
        if symbol_count > 256 or symbol_count > size - index:
            raise ImageMetadataError("JPEG: DHT の符号数が長さと整合しません")
        index += symbol_count
        tables += 1
        if tables > table_limit:
            raise ImageMetadataError(f"JPEG: 表の数が上限（{_MAX_JPEG_TABLES}）を超えています")
    if index != size:
        raise ImageMetadataError("JPEG: DHT の長さが表の構造と整合しません")
    return tables


def _find_entropy_marker(data: bytes, start: int) -> int:
    """SOS 直後のエントロピー符号データの終端（= 次のマーカーの 0xFF の位置）を返す。

    0xFF00（スタッフィング）・0xFFD0〜0xFFD7（RST）・0xFF の連続（フィル）はデータの
    一部として読み飛ばし、それ以外の「0xFF + コード」を次のマーカーとする。

    計算量: 1 バイトずつの走査はもちろん、``bytes.find(b"\\xff")`` で 0xFF ごとに Python
    側へ戻るループも、0xFF00 が密な細工データでは反復が O(n) 回になる（10MB で約 1 秒、
    0xFF の連続では約 2.7 秒）。C 実装の正規表現で「本物のマーカー」へ直接飛ぶことで、
    同じ入力を 30〜55ms、通常の写真 5MB を約 2ms で処理する。探索は
    :data:`_ENTROPY_SCAN_WINDOW` ごとに区切り、窓の境界をまたぐマーカーを取りこぼさない
    よう 1 バイト重ねて進める。

    次のマーカーが無いまま終端に達した（EOI の欠落・途中切れ）場合は ``len(data)`` を返す
    （呼び出し元が EOI を補う）。
    """
    total = len(data)
    window_start = start
    while True:
        window_end = min(window_start + _ENTROPY_SCAN_WINDOW, total)
        found = _ENTROPY_MARKER_RE.search(data, window_start, window_end)
        if found is not None:
            return found.start()
        if window_end >= total:
            return total
        window_start = window_end - 1


def _read_exif_orientation(payload: bytes) -> tuple[int, str] | None:
    """Exif APP1 のペイロードから IFD0 の Orientation（0x0112）を読む。

    戻り値は ``(値, struct のバイト順記号 "<" | ">")``。Exif でない・TIFF ヘッダが壊れて
    いる・該当エントリが無い場合は ``None``。判定条件は Chromium（Blink）の JPEG デコーダに
    揃える（TIFF ヘッダは II / MM と 42 を確認し、IFD0 のうち実際に読める範囲のエントリ
    だけを見て、型 SHORT かつ個数 1 のものだけを採用する）。表示側と同じ規則で読むことで、
    除去の前後で画面上の向きが変わらないようにする。GPS IFD 等のオフセットは一切たどらない。
    """
    if len(payload) < _EXIF_HEADER_SIZE + _TIFF_HEADER_SIZE:
        return None
    if not payload.startswith(_EXIF_IDENTIFIER):
        return None
    return _read_tiff_orientation(payload[_EXIF_HEADER_SIZE:])


def _read_tiff_orientation(tiff: bytes) -> tuple[int, str] | None:
    """TIFF 構造（Exif の本体。TIFF ヘッダから始まる）から IFD0 の Orientation を読む。

    JPEG の Exif APP1（``"Exif\\0\\0"`` の後ろ）・PNG の eXIf・WebP の EXIF で共通に使う。
    戻り値と判定条件は :func:`_read_exif_orientation` と同じ。どんなバイト列を渡しても
    ``None`` か結果を返し、例外は出さない。
    """
    if len(tiff) < _TIFF_HEADER_SIZE:
        return None
    byte_order = tiff[:2]
    if byte_order == b"II":
        endian = "<"
    elif byte_order == b"MM":
        endian = ">"
    else:
        return None
    magic, ifd0_offset = struct.unpack_from(endian + "HI", tiff, 2)
    if magic != _TIFF_MAGIC or ifd0_offset + 2 > len(tiff):
        return None
    (entry_count,) = struct.unpack_from(endian + "H", tiff, ifd0_offset)
    entries_start = ifd0_offset + 2
    readable_entries = min(
        entry_count, (len(tiff) - entries_start) // _IFD_ENTRY_SIZE, _MAX_IFD0_ENTRIES
    )
    for index in range(readable_entries):
        tag, value_type, count, value = struct.unpack_from(
            endian + "HHIH", tiff, entries_start + index * _IFD_ENTRY_SIZE
        )
        if tag == _TAG_ORIENTATION and value_type == _TIFF_TYPE_SHORT and count == 1:
            return value, endian
    return None


def _build_orientation_only_tiff(orientation: int, endian: str) -> bytes:
    """Orientation タグ 1 個だけを持つ最小の TIFF 構造（Exif の本体・26 バイト）を組み立てる。

    構成: TIFF ヘッダ（バイト順・42・IFD0 オフセット 8）+ IFD0（エントリ数 1・Orientation /
    SHORT / 個数 1 / 値・次 IFD オフセット 0）。GPS IFD・Exif IFD・サムネイル（IFD1）への
    ポインタは持たない。バイト順は元の Exif に合わせる。JPEG の APP1・PNG の eXIf・WebP の
    EXIF で共通に使う。
    """
    byte_order = b"II" if endian == "<" else b"MM"
    return (
        byte_order
        + struct.pack(endian + "HI", _TIFF_MAGIC, _TIFF_HEADER_SIZE)
        + struct.pack(endian + "H", 1)
        # SHORT 1 個は 4 バイトの値欄に左詰めで格納する（残り 2 バイトは 0）。
        + struct.pack(endian + "HHIHH", _TAG_ORIENTATION, _TIFF_TYPE_SHORT, 1, orientation, 0)
        + struct.pack(endian + "I", 0)
    )


def _build_orientation_only_exif(orientation: int, endian: str) -> bytes:
    """Orientation タグ 1 個だけを持つ最小の Exif APP1 セグメントを組み立てる。

    構成: ``"Exif\\0\\0"`` + :func:`_build_orientation_only_tiff` の TIFF 本体。
    """
    payload = b"Exif\x00\x00" + _build_orientation_only_tiff(orientation, endian)
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


# ──────────────────────────── PNG ────────────────────────────

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_CHUNK_HEADER = struct.Struct(">I4s")
_PNG_CHUNK_OVERHEAD = 12  # 長さ 4 + 種別 4 + CRC 4
_PNG_MAX_CHUNK_LENGTH = 0x7FFF_FFFF  # PNG 仕様上の上限（2^31 - 1）
_PNG_IEND_TYPE = b"IEND"
# 正規の IEND チャンク（長さ 0・CRC32("IEND")）。IEND のデータ部に何かを詰めた入力でも
# 出力は常にこの 12 バイトにする。
_PNG_IEND_CHUNK = b"\x00\x00\x00\x00IEND\xae\x42\x60\x82"
# Exif（データは TIFF ヘッダから始まり、JPEG の "Exif\0\0" は付かない）。向きだけを引き継ぐ。
_PNG_EXIF_TYPE = b"eXIf"
# 残す補助チャンク（種別の 1 文字目が小文字）。透過・色・HDR・APNG など表示結果に影響する
# ものに限る。tEXt・zTXt・iTXt（XMP を含む）・tIME のほか、caBX（C2PA）・旧仕様の exIf・
# アプリ独自チャンク等、ここに無いものはすべて落とす（eXIf は向きだけを作り直して残す）。
_PNG_KEPT_ANCILLARY_TYPES = frozenset(
    {
        b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"cICP", b"mDCV", b"cLLI",
        b"sBIT", b"bKGD", b"hIST", b"pHYs", b"sPLT", b"acTL", b"fcTL", b"fdAT",
    }
)  # fmt: skip
# 1 ファイルあたりのチャンク数の上限。実際の PNG / APNG は IDAT の分割やフレーム数を
# 含めても数千程度に収まる。
_MAX_PNG_CHUNKS = 100_000


def _strip_png(data: bytes) -> bytes:
    """PNG をチャンク単位で走査し、必須チャンクと表示に影響する補助チャンクだけを残す。

    種別の 1 文字目が大文字のチャンク（IHDR・PLTE・IDAT・IEND 等の必須チャンク）は常に
    残し、小文字のもの（補助チャンク）は :data:`_PNG_KEPT_ANCILLARY_TYPES` にあるものだけを
    残す。残すチャンクは CRC を含めバイト単位でそのまま使う（再計算不要）。IEND で打ち切り、
    それ以降の末尾データは捨てる。

    向き: 最初の eXIf チャンクの Orientation が 2〜8 なら、その位置に Orientation だけを持つ
    最小の eXIf（:func:`_build_png_orientation_chunk`。CRC は作り直したデータで計算する）を
    置き直す。1・範囲外・読めない場合は GPS 等ごと落とす。eXIf は PNG 仕様上 1 個までで
    libpng も 2 個目以降を無視するため、2 個目以降は読まずに落とす。元の eXIf の CRC は
    （残す他のチャンクと同じく）検証しない。
    """
    if not data.startswith(_PNG_SIGNATURE):
        raise ImageMetadataError("PNG: シグネチャが不正です")
    total = len(data)
    view = memoryview(data)
    output: list[bytes | memoryview] = [_PNG_SIGNATURE]
    exif_probed = False
    pos = len(_PNG_SIGNATURE)
    for _ in range(_MAX_PNG_CHUNKS):
        if pos + _PNG_CHUNK_HEADER.size > total:
            raise ImageMetadataError("PNG: IEND の前にデータが途切れています")
        length, chunk_type = _PNG_CHUNK_HEADER.unpack_from(data, pos)
        chunk_end = pos + _PNG_CHUNK_OVERHEAD + length
        if length > _PNG_MAX_CHUNK_LENGTH or chunk_end > total:
            raise ImageMetadataError("PNG: チャンク長がデータと整合しません")
        if not chunk_type.isalpha():
            # 長さの食い違いで次のチャンク境界を見失った場合もここで止まる。
            raise ImageMetadataError("PNG: チャンク種別が不正です")
        if chunk_type == _PNG_IEND_TYPE:
            output.append(_PNG_IEND_CHUNK)
            return b"".join(output)
        is_critical = (chunk_type[0] & 0x20) == 0
        if chunk_type == _PNG_EXIF_TYPE:
            if not exif_probed:
                exif_probed = True
                data_start = pos + _PNG_CHUNK_HEADER.size
                found = _read_tiff_orientation(data[data_start : data_start + length])
                if found is not None:
                    orientation, endian = found
                    if orientation in _ROTATED_ORIENTATIONS:
                        output.append(_build_png_orientation_chunk(orientation, endian))
        elif is_critical or chunk_type in _PNG_KEPT_ANCILLARY_TYPES:
            output.append(view[pos:chunk_end])
        pos = chunk_end
    raise ImageMetadataError(f"PNG: チャンク数が上限（{_MAX_PNG_CHUNKS}）を超えています")


def _build_png_orientation_chunk(orientation: int, endian: str) -> bytes:
    """Orientation タグ 1 個だけを持つ最小の eXIf チャンク（長さ・種別・TIFF 本体・CRC）。"""
    tiff = _build_orientation_only_tiff(orientation, endian)
    crc = zlib.crc32(_PNG_EXIF_TYPE + tiff)  # Python 3 の crc32 は常に符号なし 32 ビット
    return _PNG_CHUNK_HEADER.pack(len(tiff), _PNG_EXIF_TYPE) + tiff + struct.pack(">I", crc)


# ──────────────────────────── WebP ────────────────────────────

_RIFF_ID = b"RIFF"
_WEBP_ID = b"WEBP"
_RIFF_HEADER_SIZE = 12  # "RIFF" + サイズ 4 + "WEBP"
_RIFF_SIZE_BASE = 8  # RIFF サイズは先頭 8 バイト（"RIFF" + サイズ）を含まない
_WEBP_CHUNK_HEADER = struct.Struct("<4sI")
_VP8X_TYPE = b"VP8X"
_VP8X_PAYLOAD_SIZE = 10
_VP8X_FLAG_EXIF = 0x08
_VP8X_FLAG_XMP = 0x04
# Exif（データは TIFF ヘッダから始まる）。向きだけを引き継ぐ。
_WEBP_EXIF_TYPE = b"EXIF"
# 残すチャンク（WebP コンテナ仕様で画像の表示に関わるもの）。"XMP "・未知のチャンク
# （C2PA 等）は落とす（EXIF は向きだけを作り直して残す）。ANMF（アニメーションのフレーム）は
# 中身を解釈せずに残す。
_WEBP_KEPT_CHUNK_TYPES = frozenset(
    {b"VP8 ", b"VP8L", _VP8X_TYPE, b"ALPH", b"ANIM", b"ANMF", b"ICCP"}
)
# 1 ファイルあたりのチャンク数の上限（アニメーションのフレーム数を含めても十分な値）。
_MAX_WEBP_CHUNKS = 100_000


def _strip_webp(data: bytes) -> bytes:
    """WebP（RIFF）をチャンク単位で走査し、画像の表示に必要なチャンクだけを残す。

    VP8X がある場合は先頭のフラグバイトから EXIF(0x08)・XMP(0x04) ビットを落とす（実体を
    消したのにフラグが立っていると、デコーダによっては不整合として扱われるため）。RIFF
    サイズは残したチャンクから再計算し、RIFF の範囲外（末尾）のデータは捨てる。奇数長
    チャンクのパディングは 0x00 に正規化する（最後のチャンクだけパディングが欠けた入力は、
    ペイロード自体は揃っているため受け付けて補う）。

    向き: 最初の EXIF チャンクの Orientation が 2〜8 なら、その位置に Orientation だけを持つ
    最小の EXIF チャンク（:func:`_build_webp_orientation_chunk`）を置き直し、先頭の VP8X の
    EXIF フラグを立て直す。先頭のチャンクが VP8X でない（拡張形式でない）ファイルは、
    デコーダ（libwebp）がメタデータのチャンクを読まないため向きも捨てる。コンテナ仕様上 EXIF
    は 1 個までで、読み手は 2 個目以降を無視してよいため、2 個目以降は読まずに落とす。
    """
    total = len(data)
    if total < _RIFF_HEADER_SIZE or not data.startswith(_RIFF_ID) or data[8:12] != _WEBP_ID:
        raise ImageMetadataError("WebP: RIFF / WEBP ヘッダが不正です")
    (riff_size,) = struct.unpack_from("<I", data, 4)
    riff_end = _RIFF_SIZE_BASE + riff_size
    if riff_end < _RIFF_HEADER_SIZE or riff_end > total:
        raise ImageMetadataError("WebP: RIFF サイズがデータと整合しません")
    view = memoryview(data)
    chunks: list[bytes | memoryview] = []
    # 向きの引き継ぎ用（chunks 内の位置）: 先頭の VP8X のフラグバイトと、最小の EXIF チャンク。
    # EXIF は VP8X より後ろに来るため、フラグは走査を終えてから立て直す。
    vp8x_flags_index: int | None = None
    orientation_exif_index: int | None = None
    exif_probed = False
    pos = _RIFF_HEADER_SIZE
    chunk_count = 0
    while pos < riff_end:
        chunk_count += 1
        if chunk_count > _MAX_WEBP_CHUNKS:
            raise ImageMetadataError(
                f"WebP: チャンク数が上限（{_MAX_WEBP_CHUNKS}）を超えています"
            )
        if pos + _WEBP_CHUNK_HEADER.size > riff_end:
            raise ImageMetadataError("WebP: チャンクヘッダの途中でデータが途切れています")
        chunk_type, size = _WEBP_CHUNK_HEADER.unpack_from(data, pos)
        payload_start = pos + _WEBP_CHUNK_HEADER.size
        payload_end = payload_start + size
        if payload_end > riff_end:
            raise ImageMetadataError("WebP: チャンク長がデータと整合しません")
        if chunk_type == _VP8X_TYPE:
            if size != _VP8X_PAYLOAD_SIZE:
                raise ImageMetadataError("WebP: VP8X チャンクの長さが不正です")
            flags = data[payload_start] & ~(_VP8X_FLAG_EXIF | _VP8X_FLAG_XMP)
            chunks.append(view[pos:payload_start])
            if pos == _RIFF_HEADER_SIZE:
                vp8x_flags_index = len(chunks)
            chunks.append(bytes((flags,)))
            chunks.append(view[payload_start + 1 : payload_end])
        elif chunk_type == _WEBP_EXIF_TYPE:
            if not exif_probed:
                exif_probed = True
                found = _read_tiff_orientation(data[payload_start:payload_end])
                if found is not None:
                    orientation, endian = found
                    if orientation in _ROTATED_ORIENTATIONS:
                        orientation_exif_index = len(chunks)
                        chunks.append(_build_webp_orientation_chunk(orientation, endian))
        elif chunk_type in _WEBP_KEPT_CHUNK_TYPES:
            chunks.append(view[pos:payload_end])
            if size % 2:
                chunks.append(b"\x00")
        # 最後のチャンクだけパディングが欠けている場合は RIFF 終端で止める。
        pos = min(payload_end + size % 2, riff_end)
    if orientation_exif_index is not None:
        if vp8x_flags_index is None:
            chunks[orientation_exif_index] = b""
        else:
            kept_flags = chunks[vp8x_flags_index][0] | _VP8X_FLAG_EXIF
            chunks[vp8x_flags_index] = bytes((kept_flags,))
    body_size = sum(len(chunk) for chunk in chunks)
    return b"".join([_RIFF_ID, struct.pack("<I", 4 + body_size), _WEBP_ID, *chunks])


def _build_webp_orientation_chunk(orientation: int, endian: str) -> bytes:
    """Orientation タグ 1 個だけを持つ最小の EXIF チャンク（種別・長さ・TIFF 本体・パディング）。"""
    tiff = _build_orientation_only_tiff(orientation, endian)
    padding = b"\x00" * (len(tiff) % 2)  # チャンクは偶数長にそろえる（TIFF 本体は 26 バイト）
    return _WEBP_CHUNK_HEADER.pack(_WEBP_EXIF_TYPE, len(tiff)) + tiff + padding
