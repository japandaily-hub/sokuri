"""案件写真のメタデータ除去（services/image_metadata.py）と組み込み（case_photos.py）のテスト。

security review 確定指摘（MEDIUM）: 案件写真を EXIF 付きのまま保存・配信しており、承認済み
業者が成約前に依頼者の自宅の GPS 座標を取得できた。画像ライブラリには依存せず、構造が
分かっている合成バイト列で「期待する出力とバイト単位で一致するか」を検証する。

- JPEG: GPS / XMP / IPTC / COM / MPF / C2PA / EOI 以降の副画像が消え、JFIF・ICC・Adobe・
  画像のセグメントとエントロピー符号データはバイト単位で同一、向き（Orientation）だけが
  最小の Exif として残る（II / MM 両方）。
- JPEG の軽微な破損（QA 指摘 M1）: libjpeg（ブラウザ）が警告付きで表示できる EOI の欠落・
  セグメント間の余分なバイト・0xFF00・APPn の長さの過少申告は受け付け、読み飛ばした
  バイトは出力に残らない。SOS より前の途切れ・再同期の上限超過は引き続き例外。
- 長さを偽ったセグメントが後続の Exif を飲み込んでも、出力へ複製されない。ICC・サムネイル
  付き JFIF の疑いは、捨てるセグメントを挟んでも次に残すセグメントまで持ち越す（L-2）。
- Exif / XMP の目印は SOS ヘッダの中身と、通し番号順につないだ ICC プロファイル全体でも
  探す（L-3。チャンク・ヘッダの境目をまたぐものも見逃さない）。
- PNG: tEXt / iTXt / zTXt / tIME（と許可リスト外の補助チャンク）が消え、他はそのまま、
  IEND 以降が消える。eXIf は向き（2〜8）だけの最小形として同じ位置に残る（CRC 正）。
- WebP: XMP（と未知のチャンク）が消え、VP8X のフラグが落ち、RIFF サイズが正しい。EXIF は
  先頭が VP8X のときだけ向き（2〜8）だけの最小形で残り、EXIF フラグが立ち直る。
- 細工入力で ImageMetadataError 以外の例外が漏れず、出力は冪等。
- エンドポイント: アップロード時・配信時（対策以前に保存済みの写真）の両方で除去される。

フィクスチャの作法は tests/test_r12_backend_fixes.py と同じ（in-memory SQLite +
ASGITransport をローカルに複製し、トークンは create_access_token で直接発行する）。
"""

from __future__ import annotations

import logging
import random
import struct
import uuid
import zlib
from typing import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import case_photos
from app.api.v1.router import api_router
from app.config import get_settings
from app.core.security import create_access_token, hash_password
from app.db.models.user import User
from app.db.session import get_session
from app.services import image_metadata
from app.services.image_metadata import ImageMetadataError, strip_image_metadata

# ──────────────────────────── フィクスチャ ────────────────────────────


def create_test_app(session: AsyncSession) -> FastAPI:
    app = FastAPI()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    test_app = create_test_app(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def tmp_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_strip_failure_log_throttles():
    """除去失敗ログの間引き状態をテスト間で持ち越さない（log_throttle のテスト専用 API）。"""
    case_photos._upload_strip_failure_throttle.reset()
    case_photos._serve_strip_failure_throttle.reset()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user_token(db_session: AsyncSession, email: str = "owner@example.com") -> str:
    user = User(
        email=email, password_hash=hash_password("userpass123"), name="依頼者", role="user"
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return create_access_token(user.id, "user", "user")


# ──────────────────────────── 合成画像の部品（Exif / TIFF） ────────────────────────────

# 出力に残ってはならない目印。"SENTINEL" を含むバイト列は全部メタデータ側に置く。
_MAKE_SENTINEL = b"SENTINEL-CAMERA-MAKE\x00"
_GPS_LATITUDE = ((35, 1), (39, 1), (294057, 10000))  # 北緯 35°39'29.4057"
_GPS_LONGITUDE = ((139, 1), (42, 1), (123456, 10000))  # 東経 139°42'12.3456"
_ENDIANS = pytest.mark.parametrize("endian", ["<", ">"], ids=["II", "MM"])


def _rationals(endian: str, values: tuple[tuple[int, int], ...]) -> bytes:
    return b"".join(struct.pack(endian + "II", num, den) for num, den in values)


def _gps_bytes(endian: str) -> bytes:
    """GPS 緯度経度の RATIONAL 値そのもの（除去漏れの検出に使う）。"""
    return _rationals(endian, _GPS_LATITUDE) + _rationals(endian, _GPS_LONGITUDE)


def _exif_tiff(endian: str, *, orientation: int | None, with_gps: bool = True) -> bytes:
    """IFD0（Make・Orientation・GPS IFD ポインタ）と GPS IFD（緯度経度）を持つ TIFF 本体。"""
    ifd0_count = 1 + (orientation is not None) + with_gps
    gps_ifd_offset = 8 + 2 + 12 * ifd0_count + 4
    gps_ifd_size = 2 + 12 * 4 + 4 if with_gps else 0
    make_offset = gps_ifd_offset + gps_ifd_size
    latitude_offset = make_offset + len(_MAKE_SENTINEL)
    longitude_offset = latitude_offset + 24

    def entry(tag: int, value_type: int, count: int, value_field: bytes) -> bytes:
        return struct.pack(endian + "HHI", tag, value_type, count) + value_field

    def u32(value: int) -> bytes:
        return struct.pack(endian + "I", value)

    ifd0 = [entry(0x010F, 2, len(_MAKE_SENTINEL), u32(make_offset))]
    if orientation is not None:
        ifd0.append(entry(0x0112, 3, 1, struct.pack(endian + "HH", orientation, 0)))
    if with_gps:
        ifd0.append(entry(0x8825, 4, 1, u32(gps_ifd_offset)))
    tiff = (b"II" if endian == "<" else b"MM") + struct.pack(endian + "HI", 42, 8)
    tiff += struct.pack(endian + "H", ifd0_count) + b"".join(ifd0) + u32(0)
    if with_gps:
        gps_ifd = [
            entry(0x0001, 2, 2, b"N\x00\x00\x00"),
            entry(0x0002, 5, 3, u32(latitude_offset)),
            entry(0x0003, 2, 2, b"E\x00\x00\x00"),
            entry(0x0004, 5, 3, u32(longitude_offset)),
        ]
        tiff += struct.pack(endian + "H", 4) + b"".join(gps_ifd) + u32(0)
    tiff += _MAKE_SENTINEL
    if with_gps:
        tiff += _gps_bytes(endian)
    return tiff


def _minimal_tiff(endian: str, orientation: int) -> bytes:
    """除去後に残るべき最小 Exif の TIFF 本体（PNG の eXIf・WebP の EXIF のデータそのもの）。

    実装を呼ばず、仕様どおりのバイト列を手で組む。
    """
    if endian == "<":
        return (
            b"II\x2a\x00\x08\x00\x00\x00"  # バイト順・42・IFD0 オフセット 8
            + b"\x01\x00"  # エントリ数 1
            + b"\x12\x01\x03\x00\x01\x00\x00\x00"  # Orientation・SHORT・個数 1
            + bytes((orientation, 0, 0, 0))  # 値（左詰め）
            + b"\x00\x00\x00\x00"  # 次 IFD なし
        )
    return (
        b"MM\x00\x2a\x00\x00\x00\x08"
        + b"\x00\x01"
        + b"\x01\x12\x00\x03\x00\x00\x00\x01"
        + bytes((0, orientation, 0, 0))
        + b"\x00\x00\x00\x00"
    )


def _minimal_exif(endian: str, orientation: int) -> bytes:
    """除去後に残るべき最小 Exif APP1（JPEG）。"""
    return b"\xff\xe1\x00\x22" + b"Exif\x00\x00" + _minimal_tiff(endian, orientation)


# ──────────────────────────── 合成画像の部品（JPEG） ────────────────────────────


def _seg(marker: int, payload: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(payload) + 2) + payload


def _with_declared_length(segment: bytes, delta: int) -> bytes:
    """長さ欄だけを ``delta`` バイト増減させたセグメント（実データはそのまま）。"""
    (length,) = struct.unpack_from(">H", segment, 2)
    return segment[:2] + struct.pack(">H", length + delta) + segment[4:]


def _insert_after(data: bytes, anchor: bytes, extra: bytes) -> bytes:
    """1 回だけ現れる ``anchor`` の直後に ``extra`` を差し込む。"""
    assert data.count(anchor) == 1
    index = data.index(anchor) + len(anchor)
    return data[:index] + extra + data[index:]


def _exif_app1(endian: str, *, orientation: int | None, with_gps: bool = True) -> bytes:
    tiff = _exif_tiff(endian, orientation=orientation, with_gps=with_gps)
    return _seg(0xE1, b"Exif\x00\x00" + tiff)


_SOI = b"\xff\xd8"
_EOI = b"\xff\xd9"
_APP0_JFIF = _seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x48\x00\x48\x00\x00")
_APP1_XMP = _seg(
    0xE1,
    b"http://ns.adobe.com/xap/1.0/\x00"
    b'<x:xmpmeta>SENTINEL-XMP exif:GPSLatitude="35,39.49N"</x:xmpmeta>',
)
_APP1_EXTENDED_XMP = _seg(
    0xE1,
    b"http://ns.adobe.com/xmp/extension/\x00"
    + b"0" * 32
    + struct.pack(">II", 24, 0)
    + b"SENTINEL-EXTENDED-XMP-GPS",
)
# 先頭 4 バイトにプロファイル全体の長さ（128）を持つ ICC 本体（ヘッダだけの最小形）。
_ICC_PROFILE = struct.pack(">I", 128) + bytes(124)
_APP2_ICC = _seg(0xE2, b"ICC_PROFILE\x00\x01\x01" + _ICC_PROFILE)
_APP2_MPF = _seg(0xE2, b"MPF\x00II*\x00\x08\x00\x00\x00SENTINEL-MPF")
_APP11_C2PA = _seg(0xEB, b"JP\x00\x01\x00\x00\x00\x01SENTINEL-C2PA-JUMBF")
_APP13_IPTC = _seg(0xED, b"Photoshop 3.0\x008BIM\x04\x04\x00\x00\x00\x00\x00\x12SENTINEL-IPTC-CITY")
_APP14_ADOBE = _seg(0xEE, b"Adobe\x00\x64\x00\x00\x00\x00\x01")
_COM = _seg(0xFE, b"SENTINEL-COMMENT")
_DQT = _seg(0xDB, b"\x00" + bytes(range(1, 65)))
_SOF0 = _seg(0xC0, b"\x08\x00\x10\x00\x10\x01\x01\x11\x00")
_DHT = _seg(
    0xC4, b"\x00" + bytes((0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0)) + bytes(range(12))
)
_DRI = _seg(0xDD, b"\x00\x02")
_SOS_1 = _seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
# スタッフィング（FF00）・RST（FFD0〜FFD7）を含み、末尾のフィルバイト（FF）で次の
# マーカーへつながるエントロピー符号データ。
_ENTROPY_1 = b"\x12\x34\xff\x00\x56\xff\xd0\x78\x9a\xff\x00\xff\xd1\xbc\xde\xff"
_DHT_2 = _seg(
    0xC4, b"\x10" + bytes((0, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)) + b"\x01\x02\x03"
)
_SOS_2 = _seg(0xDA, b"\x01\x01\x10\x01\x3f\x00")
_ENTROPY_2 = b"\xab\xff\x00\xcd\xff\xd7\xef\x01\xff\x00"
# SOI の後ろに続ける最小の画像部分（量子化表・フレーム・スキャン・EOI）。
_JPEG_BODY = _DQT + _SOF0 + _SOS_1 + _ENTROPY_2 + _EOI
# メタデータを持たない最小構成（除去の対象が無いので入出力が一致すべきもの）。
_CLEAN_JPEG = _SOI + _APP0_JFIF + _DQT + _SOF0 + _DHT + _SOS_1 + _ENTROPY_2 + _EOI


def _jpeg_with_metadata(
    endian: str, *, orientation: int | None = 6, trailer: bool = True
) -> tuple[bytes, bytes]:
    """（入力, 期待する出力）の組を返す。

    入力は実機写真で典型的なメタデータ一式（Exif の GPS・XMP・拡張 XMP・IPTC・COM・MPF・
    C2PA）と、EOI の後ろに連結された「GPS 付き Exif を持つ副画像」（MPF の副画像・
    Ultra HDR のゲインマップ・Motion Photo 相当）を持つ。フィルバイト付きのマーカー・
    スキャン間の COM・2 回目のスキャン（プログレッシブ相当）も含める。
    """
    secondary_image = (
        _SOI + _exif_app1(endian, orientation=1) + _DQT + _SOF0 + _DHT + _SOS_1 + b"\x01" + _EOI
    )
    original = (
        _SOI
        + _APP0_JFIF
        + _exif_app1(endian, orientation=orientation)
        + _APP1_XMP
        + _APP1_EXTENDED_XMP
        + _APP13_IPTC
        + _COM
        + _APP2_ICC
        + _APP2_MPF
        + _APP11_C2PA
        + _APP14_ADOBE
        + b"\xff\xff"  # フィルバイト（マーカー前の 0xFF の連続）
        + _DQT
        + _SOF0
        + _DHT
        + _DRI
        + _SOS_1
        + _ENTROPY_1
        + _DHT_2
        + _COM  # スキャン間の COM も落ちる
        + _SOS_2
        + _ENTROPY_2
        + _EOI
    )
    if trailer:
        original += secondary_image + b"SENTINEL-TRAILER"
    rotated = orientation is not None and 2 <= orientation <= 8
    expected = (
        _SOI
        + _APP0_JFIF
        + (_minimal_exif(endian, orientation) if rotated else b"")
        + _APP2_ICC
        + _APP14_ADOBE
        + _DQT
        + _SOF0
        + _DHT
        + _DRI
        + _SOS_1
        + _ENTROPY_1
        + _DHT_2
        + _SOS_2
        + _ENTROPY_2
        + _EOI
    )
    return original, expected


# ──────────────────────────── 合成画像の部品（PNG / WebP） ────────────────────────────

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


_IHDR = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
_IDAT_STREAM = zlib.compress(b"\x00" + b"\x10\x20\x30" * 2 + b"\x00" + b"\x40\x50\x60" * 2)
_IDAT_1 = _png_chunk(b"IDAT", _IDAT_STREAM[:7])
_IDAT_2 = _png_chunk(b"IDAT", _IDAT_STREAM[7:])
_IEND = _png_chunk(b"IEND", b"")
_PNG_KEPT_ANCILLARY = (
    _png_chunk(b"sRGB", b"\x00"),
    _png_chunk(b"gAMA", struct.pack(">I", 45455)),
    _png_chunk(b"iCCP", b"icc\x00\x00" + zlib.compress(b"profile")),
    _png_chunk(b"pHYs", struct.pack(">IIB", 2835, 2835, 1)),
    _png_chunk(b"tRNS", b"\x00\x01\x00\x02\x00\x03"),
)
_CLEAN_PNG = _PNG_SIGNATURE + _IHDR + _IDAT_1 + _IDAT_2 + _IEND


def _png_with_metadata(*, trailer: bool = True) -> tuple[bytes, bytes]:
    """（入力, 期待する出力）の組を返す。

    eXIf（Orientation=6・GPS 付き）は、同じ位置の「向きだけの最小 eXIf」に置き直される。
    """
    srgb, gama, iccp, phys, trns = _PNG_KEPT_ANCILLARY
    original = (
        _PNG_SIGNATURE
        + _IHDR
        + srgb
        + gama
        + _png_chunk(b"tEXt", b"GPSLatitude\x00SENTINEL-PNG-TEXT")
        + iccp
        + phys
        + _png_chunk(b"eXIf", _exif_tiff("<", orientation=6))
        + _png_chunk(b"zTXt", b"Raw profile type exif\x00\x00" + zlib.compress(b"SENTINEL-ZTXT"))
        + _png_chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00<x>SENTINEL-PNG-XMP</x>")
        + _png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 9, 24, 9, 30, 0))
        + trns
        + _IDAT_1
        + _png_chunk(b"caBX", b"SENTINEL-PNG-C2PA")  # 許可リスト外（C2PA）
        + _IDAT_2
        + _png_chunk(b"exIf", _exif_tiff(">", orientation=None))  # 旧仕様の Exif チャンク
        + _IEND
    )
    if trailer:
        original += b"SENTINEL-PNG-TRAILER" + _png_chunk(b"eXIf", _exif_tiff("<", orientation=1))
    expected = (
        _PNG_SIGNATURE
        + _IHDR
        + srgb
        + gama
        + iccp
        + phys
        + _png_chunk(b"eXIf", _minimal_tiff("<", 6))
        + trns
        + _IDAT_1
        + _IDAT_2
        + _IEND
    )
    return original, expected


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes, int]]:
    """PNG を（種別, データ, CRC）の列に分解する（実装を使わないテスト側の読み取り）。"""
    assert data.startswith(_PNG_SIGNATURE)
    chunks, pos = [], len(_PNG_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        (crc,) = struct.unpack_from(">I", data, pos + 8 + length)
        chunks.append((data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length], crc))
        pos += 12 + length
    return chunks


def _webp_chunk(fourcc: bytes, payload: bytes) -> bytes:
    padding = b"\x00" if len(payload) % 2 else b""
    return fourcc + struct.pack("<I", len(payload)) + payload + padding


def _riff_webp(body: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def _vp8x(flags: int) -> bytes:
    # フラグ 1・予約 3・キャンバス幅-1（3 バイト）・高さ-1（3 バイト）の 10 バイト。
    return _webp_chunk(b"VP8X", bytes((flags, 0, 0, 0)) + b"\x01\x00\x00" + b"\x01\x00\x00")


_WEBP_FLAG_ICC, _WEBP_FLAG_ALPHA, _WEBP_FLAG_EXIF, _WEBP_FLAG_XMP = 0x20, 0x10, 0x08, 0x04
_WEBP_ICCP = _webp_chunk(b"ICCP", b"icc-profile-body")
_WEBP_ALPH = _webp_chunk(b"ALPH", b"\x00\xff\xff\xff\xff")  # 奇数長（パディング付き）
# 奇数長（パディング付き）の VP8 ビットストリーム（キーフレームヘッダ + 詰め物）。
_WEBP_VP8 = _webp_chunk(b"VP8 ", b"\x30\x01\x00\x9d\x01\x2a\x02\x00\x02\x00" + b"\x00" * 7)
_CLEAN_WEBP = _riff_webp(_WEBP_VP8)


def _webp_with_metadata(*, trailer: bool = True) -> tuple[bytes, bytes]:
    """（入力, 期待する出力）の組を返す。

    EXIF（Orientation=6・GPS 付き）は、同じ位置の「向きだけの最小 EXIF」に置き直される。
    """
    all_flags = _WEBP_FLAG_ICC | _WEBP_FLAG_ALPHA | _WEBP_FLAG_EXIF | _WEBP_FLAG_XMP
    original = _riff_webp(
        _vp8x(all_flags)
        + _WEBP_ICCP
        + _WEBP_ALPH
        + _WEBP_VP8
        + _webp_chunk(b"EXIF", _exif_tiff("<", orientation=6))
        + _webp_chunk(b"XMP ", b"<x:xmpmeta>SENTINEL-WEBP-XMP</x:xmpmeta>")
        + _webp_chunk(b"C2PA", b"SENTINEL-WEBP-C2PA")  # 未知のチャンク
    )
    if trailer:
        original += b"SENTINEL-WEBP-TRAILER"
    expected = _riff_webp(
        _vp8x(_WEBP_FLAG_ICC | _WEBP_FLAG_ALPHA | _WEBP_FLAG_EXIF)
        + _WEBP_ICCP
        + _WEBP_ALPH
        + _WEBP_VP8
        + _webp_chunk(b"EXIF", _minimal_tiff("<", 6))
    )
    return original, expected


# 形式ごとの（入力, 期待出力）生成関数。trailer=False は「末尾データ無し」の完全な画像。
_SAMPLES: dict[str, Callable[..., tuple[bytes, bytes]]] = {
    "jpeg": lambda trailer=True: _jpeg_with_metadata("<", trailer=trailer),
    "png": _png_with_metadata,
    "webp": _webp_with_metadata,
}
_FORMATS = pytest.mark.parametrize("ext", ["jpeg", "png", "webp"])


# ──────────────────────────── JPEG ────────────────────────────


@_ENDIANS
def test_jpeg_strips_all_metadata_and_keeps_image_bytes(endian: str):
    original, expected = _jpeg_with_metadata(endian)
    stripped = strip_image_metadata(original, "jpeg")

    assert stripped == expected
    assert _gps_bytes(endian) not in stripped
    assert b"SENTINEL" not in stripped
    assert b"http://ns.adobe.com" not in stripped
    assert b"MPF\x00" not in stripped
    assert stripped.count(b"Exif\x00\x00") == 1
    assert stripped.endswith(_EOI)


def test_jpeg_orientation_only_exif_has_exact_layout():
    """最小 Exif の実バイト（II・Orientation=6）を 16 進で固定する。"""
    original, _ = _jpeg_with_metadata("<", orientation=6)
    stripped = strip_image_metadata(original, "jpg")
    assert bytes.fromhex(
        "ffe10022" "457869660000" "49492a0008000000" "0100" "120103000100000006000000" "00000000"
    ) in stripped


@_ENDIANS
@pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
def test_jpeg_keeps_rotated_orientation_as_minimal_exif(endian: str, orientation: int):
    original, expected = _jpeg_with_metadata(endian, orientation=orientation)
    assert strip_image_metadata(original, "jpeg") == expected


@_ENDIANS
@pytest.mark.parametrize("orientation", [None, 0, 1, 9, 0xFFFF])
def test_jpeg_drops_exif_entirely_when_orientation_is_upright_or_invalid(
    endian: str, orientation: int | None
):
    original, expected = _jpeg_with_metadata(endian, orientation=orientation)
    stripped = strip_image_metadata(original, "jpeg")
    assert stripped == expected
    assert b"Exif" not in stripped


def test_jpeg_without_metadata_passes_through_unchanged():
    assert strip_image_metadata(_CLEAN_JPEG, "jpeg") == _CLEAN_JPEG


def test_jpeg_orientation_comes_from_first_exif_that_has_one():
    """Chromium と同じく「Orientation を読めた最初の Exif」を採用し、その位置に置き直す。"""
    original = (
        _SOI
        + _exif_app1("<", orientation=None)
        + _APP0_JFIF
        + _exif_app1(">", orientation=3)
        + _exif_app1("<", orientation=8)
        + _JPEG_BODY
    )
    expected = _SOI + _APP0_JFIF + _minimal_exif(">", 3) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == expected


@pytest.mark.parametrize(
    "exif_payload",
    [
        b"Exif\x00\x00",  # TIFF ヘッダ無し
        b"Exif\x00\x00XX\x2a\x00\x08\x00\x00\x00",  # バイト順が不正
        b"Exif\x00\x00II\x2b\x00\x08\x00\x00\x00",  # 42 でない
        b"Exif\x00\x00II\x2a\x00\xff\xff\x00\x00",  # IFD0 オフセットが範囲外
        b"Exif\x00\x00II\x2a\x00\x08\x00\x00\x00\x05\x00\x12\x01\x03\x00",  # エントリ途中で切れ
        b"Exif\x00\x00II\x2a\x00\x08\x00\x00\x00\x01\x00\x12\x01\x04\x00\x01\x00\x00\x00\x06\x00\x00\x00",
        b"Exif\x00\x00II\x2a\x00\x08\x00\x00\x00\x01\x00\x12\x01\x03\x00\x02\x00\x00\x00\x06\x00\x00\x00",
    ],
    ids=[
        "no-tiff", "bad-byte-order", "bad-magic", "ifd-out-of-range", "truncated-ifd",
        "long-type", "count-2",
    ],
)
def test_jpeg_drops_unreadable_exif_without_error(exif_payload: bytes):
    """Exif が壊れていても画像自体は正常なら、Exif を丸ごと捨てて成功する（向きは正立扱い）。"""
    original = _SOI + _seg(0xE1, exif_payload) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == _SOI + _JPEG_BODY


@pytest.mark.parametrize(
    ("segment", "kept"),
    [
        (_APP0_JFIF, True),
        # サムネイル（1×1 RGB）付きの JFIF は本来の長さどおりなのでそのまま残る。
        (_seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x48\x00\x48\x01\x01\x10\x20\x30"), True),
        (_seg(0xE0, b"JFXX\x00\x10" + b"\x00" * 16), False),  # JFIF 拡張（サムネイル）
        (_seg(0xE0, b"AVI1\x00" + b"\x00" * 8), False),
        (_APP2_ICC, True),
        (_APP2_MPF, False),
        (_seg(0xE2, b"FPXR\x00" + b"\x00" * 8), False),  # FlashPix
        (_APP14_ADOBE, True),
        (_seg(0xEE, b"NotAdobe"), False),
        (_seg(0xE3, b"Meta\x00SENTINEL"), False),  # APP3
        (_APP11_C2PA, False),
        (_APP13_IPTC, False),
        (_seg(0xEF, b"SENTINEL-APP15"), False),
        (_COM, False),
    ],
)
def test_jpeg_app_segment_allowlist(segment: bytes, kept: bool):
    expected = _SOI + (segment if kept else b"") + _JPEG_BODY
    assert strip_image_metadata(_SOI + segment + _JPEG_BODY, "jpeg") == expected


@pytest.mark.parametrize("window", [2, 3, 4, 5, 7, 16, 64])
def test_jpeg_entropy_scan_window_boundaries_do_not_change_output(monkeypatch, window: int):
    """走査窓をどこで区切っても（マーカー・FF00・RST・フィルが境界をまたいでも）結果は同じ。"""
    monkeypatch.setattr(image_metadata, "_ENTROPY_SCAN_WINDOW", window)
    for endian in ("<", ">"):
        original, expected = _jpeg_with_metadata(endian)
        assert strip_image_metadata(original, "jpeg") == expected
        # EOI が無く終端まで走査する経路も窓の区切りに依存しない。
        truncated = _jpeg_with_metadata(endian, trailer=False)[0][: -len(_EOI)]
        assert strip_image_metadata(truncated, "jpeg") == expected


def test_jpeg_large_scan_is_kept_byte_for_byte():
    """実写真相当（約 3MB・0xFF を 0x00 で詰めた乱数）のスキャンが既定の窓で丸ごと残る。"""
    entropy = random.Random(1).randbytes(3 * 1024 * 1024).replace(b"\xff", b"\xff\x00")
    image = _SOI + _APP0_JFIF + _DQT + _SOF0 + _DHT + _SOS_1 + entropy + _EOI
    original = image[:2] + _exif_app1("<", orientation=None) + image[2:]
    assert strip_image_metadata(original, "jpeg") == image


# ──────────────── JPEG: libjpeg が警告付きで表示できる破損は受け付ける（QA M1） ────────────────

_EXIF_II_6 = _exif_app1("<", orientation=6)  # _jpeg_with_metadata("<") に入る Exif
_JUNK = b"\x00\x13\x37\x00"  # セグメント間に紛れ込んだ余分なバイト（0xFF を含まない）


def _drop_eoi(data: bytes) -> bytes:
    return data[: -len(_EOI)]


def _insert_junk_between_segments(data: bytes) -> bytes:
    # 捨てるセグメント（Exif）の後ろ・残すセグメント（DQT）の後ろ・スキャン間（DHT）の後ろ。
    for anchor in (_EXIF_II_6, _DQT, _DHT_2):
        data = _insert_after(data, anchor, _JUNK)
    return data


def _insert_stuffed_zero_between_segments(data: bytes) -> bytes:
    data = _insert_after(data, _APP14_ADOBE, b"\xff\x00")
    return _insert_after(data, _SOF0, b"\xff\xff\x00")  # フィル付きの 0xFF00


def _declare_app_segments_one_byte_short(data: bytes) -> bytes:
    for segment in (_EXIF_II_6, _APP13_IPTC, _COM):
        data = data.replace(segment, _with_declared_length(segment, -1))
    return data


def _all_corruptions(data: bytes) -> bytes:
    # 差し込み位置の目印（元のセグメント）が残っているうちに差し込み、最後に長さを書き換える。
    data = _insert_stuffed_zero_between_segments(_insert_junk_between_segments(data))
    return _drop_eoi(_declare_app_segments_one_byte_short(data))


@pytest.mark.parametrize(
    "corrupt",
    [
        _drop_eoi,
        _insert_junk_between_segments,
        _insert_stuffed_zero_between_segments,
        _declare_app_segments_one_byte_short,
        _all_corruptions,
    ],
    ids=["missing-eoi", "junk-between-segments", "ff00-between-segments", "app-length-short",
         "all-combined"],
)
def test_jpeg_tolerates_corruptions_that_browsers_display(corrupt):
    """読み飛ばした部分（余分なバイト・FF00・短く申告した APPn の残り）は出力に残らず、
    画像部分と向きは完全な場合とバイト単位で同一、EOI で終わる。"""
    complete, expected = _jpeg_with_metadata("<", trailer=False)
    stripped = strip_image_metadata(corrupt(complete), "jpeg")

    assert stripped == expected
    assert _JUNK not in stripped
    assert b"SENTINEL" not in stripped
    assert _gps_bytes("<") not in stripped
    assert stripped.endswith(_EOI)


def test_jpeg_missing_eoi_after_trailing_ff_keeps_it_as_fill():
    """スキャンが 0xFF で途切れた場合も EOI を補う（残った 0xFF は EOI 前のフィルになる）。"""
    complete, expected = _jpeg_with_metadata("<", trailer=False)
    assert strip_image_metadata(complete[:-1], "jpeg") == expected[:-2] + b"\xff" + _EOI


def test_jpeg_truncation_after_first_scan_is_completed_with_eoi():
    """最初の SOS ヘッダより前で途切れたものは例外、以降で途切れたものは EOI を補って受け付ける。"""
    complete, expected = _jpeg_with_metadata("<", trailer=False)
    first_scan_data = complete.index(_SOS_1) + len(_SOS_1)
    header = expected[: expected.index(_SOS_1) + len(_SOS_1)]
    for cut in range(len(complete)):
        truncated = complete[:cut]
        if cut < first_scan_data:
            with pytest.raises(ImageMetadataError):
                strip_image_metadata(truncated, "jpeg")
            continue
        stripped = strip_image_metadata(truncated, "jpeg")
        assert stripped.startswith(header)
        assert stripped.endswith(_EOI)
        assert b"SENTINEL" not in stripped
        assert _gps_bytes("<") not in stripped
        assert strip_image_metadata(stripped, "jpeg") == stripped


def test_jpeg_parameterless_markers_between_segments_are_dropped():
    original = _SOI + b"\xff\xd0" + _APP0_JFIF + b"\xff\x01" + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == _SOI + _APP0_JFIF + _JPEG_BODY


@pytest.mark.parametrize("declared_length", [0, 1])
def test_jpeg_droppable_segment_with_length_below_two_is_treated_as_empty(declared_length: int):
    """libjpeg と同じく、APPn / COM の長さ 0・1 は「中身なし」として次のマーカーを探す。"""
    original = _SOI + b"\xff\xfe" + struct.pack(">H", declared_length) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == _SOI + _JPEG_BODY


def test_jpeg_resync_distance_limit(monkeypatch):
    monkeypatch.setattr(image_metadata, "_MAX_RESYNC_BYTES", 8)
    within = _SOI + _APP0_JFIF + b"\x00" * 8 + _JPEG_BODY
    assert strip_image_metadata(within, "jpeg") == _SOI + _APP0_JFIF + _JPEG_BODY
    with pytest.raises(ImageMetadataError, match="再同期"):
        strip_image_metadata(_SOI + _APP0_JFIF + b"\x00" * 9 + _JPEG_BODY, "jpeg")


def test_jpeg_resync_count_limit(monkeypatch):
    monkeypatch.setattr(image_metadata, "_MAX_JPEG_RESYNCS", 2)
    twice = _SOI + _APP0_JFIF + b"\x00" + _DQT + b"\x00" + _SOF0 + _SOS_1 + _ENTROPY_2 + _EOI
    assert strip_image_metadata(twice, "jpeg") == _SOI + _APP0_JFIF + _JPEG_BODY
    three_times = _insert_after(twice, _SOF0, b"\x00")
    with pytest.raises(ImageMetadataError, match="再同期"):
        strip_image_metadata(three_times, "jpeg")


# ──────────────── JPEG: 長さを偽ったセグメントが後続の Exif を運ばない ────────────────


@pytest.mark.parametrize(
    ("kept_segment", "swallowed_size", "expected_segment"),
    [
        # 直後の Exif を丸ごと飲み込む（次のマーカーは申告長のちょうど後ろ）→ 本来の長さへ。
        (_APP0_JFIF, len(_EXIF_II_6), _APP0_JFIF),  # 固定部 14 バイト（サムネイル無し）
        (_APP14_ADOBE, len(_EXIF_II_6), _APP14_ADOBE),  # 12 バイト
        (_APP2_ICC, len(_EXIF_II_6), _APP2_ICC),  # プロファイル自身の申告長（128）
        # Exif の途中まで飲み込む（残りは読み飛ばす）。
        (_APP0_JFIF, 10, _APP0_JFIF),
        (_APP14_ADOBE, 10, _APP14_ADOBE),
        (_APP2_ICC, 10, b""),  # ICC の直後で再同期が起きるため ICC ごと落とす
    ],
    ids=["jfif-whole", "adobe-whole", "icc-whole", "jfif-partial", "adobe-partial", "icc-partial"],
)
def test_jpeg_kept_app_segment_declared_too_long_is_trimmed(
    kept_segment: bytes, swallowed_size: int, expected_segment: bytes
):
    """長さを偽って直後の Exif（GPS 付き）を飲み込んだ JFIF / Adobe / ICC は本来の長さに
    切り詰められ（ICC の途中飲み込みは丸ごと落とされ）、飲み込まれた Exif は出力に残らない。"""
    original = (
        _SOI + _with_declared_length(kept_segment, swallowed_size) + _EXIF_II_6 + _JPEG_BODY
    )
    stripped = strip_image_metadata(original, "jpeg")

    assert stripped == _SOI + expected_segment + _JPEG_BODY
    assert _gps_bytes("<") not in stripped
    assert b"SENTINEL" not in stripped


@pytest.mark.parametrize(
    "kept_segment", [_DQT, _DHT, _SOF0, _DRI, _SOS_1], ids=["dqt", "dht", "sof", "dri", "sos"]
)
def test_jpeg_image_segment_declared_too_long_raises(kept_segment: bytes):
    """画素に使うセグメントは構造と長さを突き合わせ、後続の Exif を飲み込んだものは例外。"""
    original = (
        _SOI
        + _DQT
        + _SOF0
        + _with_declared_length(kept_segment, len(_EXIF_II_6))
        + _EXIF_II_6
        + _JPEG_BODY
    )
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(original, "jpeg")


def _delete_inside(segment: bytes, offset: int, size: int) -> bytes:
    """長さ欄はそのままで、ペイロードの ``offset`` から ``size`` バイトを削ったセグメント。

    申告長は変わらないため、削った分だけ直後のセグメントの先頭を飲み込むことになる。
    """
    start = 4 + offset
    return segment[:start] + segment[start + size :]


_JFIF_WITH_THUMBNAIL = _seg(
    0xE0, b"JFIF\x00\x01\x01\x00\x00\x48\x00\x48\x03\x03" + bytes(range(27))  # 3×3 RGB
)


@pytest.mark.parametrize(
    "icc_and_following",
    [
        # ICC の中身が削られ、直後の MPF（TIFF ヘッダ付き）を飲み込む。
        _delete_inside(_APP2_ICC, 60, 24) + _APP2_MPF,
        # 同じく直後の Exif（GPS 付き）を飲み込む。
        _delete_inside(_APP2_ICC, 60, 40) + _EXIF_II_6,
        # 飲み込みが短く目印に届かなくても、直後で再同期が起きるため疑わしいとみなす。
        _delete_inside(_APP2_ICC, 60, 8) + _EXIF_II_6,
        # 後続セグメントのヘッダ（目印）ごと失われ、中身だけを飲み込んだ二重の破損
        # （飲み込みが画像部分に届かないよう、後ろに余分なバイトを置く）。
        _delete_inside(_APP2_ICC, 60, 24) + _APP2_MPF[16:] + _JUNK * 4,
        # 正常な ICC の直後に余分なバイトがある場合も、区別できないため同じく落とす。
        _APP2_ICC + _JUNK,
    ],
    ids=["swallows-mpf", "swallows-exif", "short-swallow", "headerless-swallow", "junk-after"],
)
def test_jpeg_icc_followed_by_resync_is_dropped(icc_and_following: bytes):
    """ICC の直後で再同期が起きたら、中身が削られて後続を飲み込んだ疑いがあるため ICC を全部
    落とす（色が sRGB 扱いになるだけで、写真自体は受け付ける）。"""
    stripped = strip_image_metadata(_SOI + icc_and_following + _JPEG_BODY, "jpeg")
    assert stripped == _SOI + _JPEG_BODY
    assert b"SENTINEL" not in stripped
    assert _gps_bytes("<") not in stripped


def test_jpeg_jfif_thumbnail_followed_by_resync_is_dropped():
    """サムネイル付き JFIF の直後で再同期が起きたら、サムネイルを落として固定部だけ残す。"""
    original = _SOI + _JFIF_WITH_THUMBNAIL + _JUNK + _JPEG_BODY
    expected = _SOI + _seg(0xE0, _JFIF_WITH_THUMBNAIL[4:18]) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == expected
    # 再同期が無ければサムネイルごと残る。
    clean = _SOI + _JFIF_WITH_THUMBNAIL + _JPEG_BODY
    assert strip_image_metadata(clean, "jpeg") == clean


@pytest.mark.parametrize(
    ("dropped", "rebuilt"),
    [
        (_COM, b""),
        (_APP13_IPTC, b""),
        (_APP2_MPF, b""),  # ICC でない APP2
        (b"\xff\x01", b""),  # TEM
        (b"\xff\xd3", b""),  # RST
        (b"\xff\xfe\x00\x00", b""),  # 長さ 0 の COM（中身なしとして読み飛ばす）
        (_seg(0xDC, b"\x00\x10\x00"), b""),  # 長さの違う DNL
        # 向きだけ作り直した最小の Exif は、元の APP1 を残したものではない。
        (_EXIF_II_6, _minimal_exif("<", 6)),
    ],
    ids=["com", "app13", "app2-mpf", "tem", "rst", "com-length-0", "dnl-bad-length", "exif"],
)
def test_jpeg_icc_then_dropped_segment_then_resync_is_dropped(dropped: bytes, rebuilt: bytes):
    """L-2: ICC の後に捨てるセグメントを挟んでから再同期が起きても、ICC を全部落とす
    （疑いは次に残すセグメントを処理するまで持ち越す）。"""
    original = _SOI + _APP2_ICC + dropped + _JUNK + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == _SOI + rebuilt + _JPEG_BODY


def test_jpeg_jfif_thumbnail_then_dropped_segment_then_resync_is_trimmed():
    """L-2: サムネイル付き JFIF の後に捨てるセグメントを挟んだ再同期でも、サムネイルを落とす。"""
    original = _SOI + _JFIF_WITH_THUMBNAIL + _COM + b"\xff\xd0" + _JUNK + _JPEG_BODY
    expected = _SOI + _seg(0xE0, _JFIF_WITH_THUMBNAIL[4:18]) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == expected


def test_jpeg_icc_swallowing_bytes_that_look_like_com_is_dropped():
    """L-2 の実例: 中身が削られた ICC が直後の IPTC の見出し（マーカー・長さ・識別子）を
    飲み込み、飲み込んだ残りが偶然 COM の形をしていると、再同期はその COM の後ろで起きる。
    それでも ICC ごと落とし、飲み込んだ IPTC の見出しを出力へ複製しない。"""
    iptc_identifier = b"Photoshop 3.0\x00"
    iptc = _seg(0xED, iptc_identifier + b"\xff\xfe\x00\x04zz" + b"8BIM\x04\x04SENTINEL-IPTC")
    swallowed_size = 4 + len(iptc_identifier)  # IPTC のマーカー・長さ・識別子
    original = _SOI + _delete_inside(_APP2_ICC, 60, swallowed_size) + iptc + _JPEG_BODY

    stripped = strip_image_metadata(original, "jpeg")

    assert stripped == _SOI + _JPEG_BODY
    assert b"Photoshop" not in stripped
    assert b"SENTINEL" not in stripped


@pytest.mark.parametrize(
    "kept_next", [_APP14_ADOBE, _APP0_JFIF, _DQT], ids=["adobe", "jfif", "dqt"]
)
def test_jpeg_resync_after_next_kept_segment_keeps_icc(kept_next: bytes):
    """ICC の疑いは次に残すセグメントで解消し、その後ろの再同期では ICC を落とさない。"""
    original = _SOI + _APP2_ICC + _COM + kept_next + _JUNK + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == _SOI + _APP2_ICC + kept_next + _JPEG_BODY


@pytest.mark.parametrize(
    "broken",
    [
        _SOI + _delete_inside(_JFIF_WITH_THUMBNAIL, 14, 20) + _EXIF_II_6 + _JPEG_BODY,
        _SOI + _delete_inside(_DQT, 1, 20) + _EXIF_II_6 + _SOF0 + _SOS_1 + _ENTROPY_2 + _EOI,
    ],
    ids=["jfif-thumbnail-swallows-exif", "dqt-swallows-exif"],
)
def test_jpeg_kept_segment_with_deleted_content_carrying_exif_raises(broken: bytes):
    """長さは整合したまま中身が削られ、後続の Exif の TIFF ヘッダを飲み込んだ JFIF / DQT は例外。"""
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "jpeg")


_SCAN_PREFIX = _SOI + _DQT + _SOF0 + _SOS_1 + _ENTROPY_2  # EOI の直前まで


@pytest.mark.parametrize(
    "broken",
    [
        _SCAN_PREFIX + _EXIF_II_6[4:] + _EOI,  # EOI と APP1 マーカーが欠けた Exif（MM も同様）
        _SCAN_PREFIX + _exif_app1(">", orientation=6)[5:],  # 同・先頭も欠けて EOI 無しで終わる
        _SCAN_PREFIX + _APP1_XMP[4:],  # EOI と APP1 マーカーが欠けた XMP
        _jpeg_with_metadata("<")[0].replace(_ENTROPY_2 + _EOI + _SOI + b"\xff\xe1\x00", _ENTROPY_2),
    ],
    ids=["exif-le", "exif-be-no-eoi", "xmp", "secondary-image-exif"],
)
def test_jpeg_metadata_absorbed_into_scan_data_raises(broken: bytes):
    """マーカーが欠けて後続の Exif / XMP がスキャンデータに吸収された場合は、複製せず例外
    （QA の前提「エントロピーデータにメタデータは入り得ない」は壊れたファイルでは崩れる）。"""
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "jpeg")


# 4 成分の SOS ヘッダ（成分数 1・成分指定 8・Ss/Se/AhAl 3 の 12 バイト）は長さの検証を通る。
@pytest.mark.parametrize(
    "scan",
    [
        _seg(0xDA, b"\x04" + b"II*\x00\x08\x00\x00\x00" + b"\x00\x3f\x00") + _ENTROPY_2,
        _seg(0xDA, b"\x04" + b"MM\x00*\x00\x00\x00\x08" + b"\x00\x3f\x00") + _ENTROPY_2,
        # SOS ヘッダの末尾からスキャンデータの先頭へまたがる目印。
        _seg(0xDA, b"\x04" + b"\x01\x00\x02\x00\x03\x00II" + b"*\x00\x08")
        + b"\x00\x00\x00"
        + _ENTROPY_2,
        _seg(0xDA, b"\x04" + b"http://ns.a") + b"dobe.com/" + _ENTROPY_2,
    ],
    ids=["tiff-le-in-header", "tiff-be-in-header", "tiff-across-header", "xmp-across-header"],
)
def test_jpeg_metadata_signature_in_scan_header_raises(scan: bytes):
    """L-3: SOS ヘッダの中身（とスキャンデータとの境目）にある Exif / XMP の目印も例外。"""
    with pytest.raises(ImageMetadataError, match="画像データの中に"):
        strip_image_metadata(_SOI + _DQT + _SOF0 + scan + _EOI, "jpeg")


@pytest.mark.parametrize(
    "broken",
    [
        _SCAN_PREFIX + _DQT + _SOF0 + _SOS_1 + _ENTROPY_2 + _EOI,  # EOI が欠けて副画像まで読む
        _SOI + _DQT + _SOS_1 + _ENTROPY_2 + _EOI,  # SOF より前に SOS
    ],
    ids=["duplicate-sof", "sos-before-sof"],
)
def test_jpeg_frame_order_violations_raise(broken: bytes):
    """libjpeg も致命エラーにするフレーム構造の違反（SOF の重複・SOF 前の SOS）は例外。"""
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "jpeg")


def _icc_chunks(profile: bytes, sizes: list[int], *, count: int | None = None) -> list[bytes]:
    """ICC 本体を ``sizes`` バイトずつに分けた APP2 セグメント列（通し番号 1 から）。"""
    chunks, offset = [], 0
    for sequence, size in enumerate(sizes, start=1):
        header = b"ICC_PROFILE\x00" + bytes((sequence, count or len(sizes)))
        chunks.append(_seg(0xE2, header + profile[offset : offset + size]))
        offset += size
    return chunks


_ICC_PROFILE_300 = struct.pack(">I", 300) + bytes(range(256)) + bytes(40)


def test_jpeg_multi_chunk_icc_is_kept_when_consistent():
    chunks = _icc_chunks(_ICC_PROFILE_300, [200, 100])
    original = _SOI + b"".join(chunks) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == original


@pytest.mark.parametrize(
    "icc_segments",
    [
        _icc_chunks(_ICC_PROFILE_300, [200], count=2),  # 2 個目が欠落
        _icc_chunks(_ICC_PROFILE_300, [200, 100])[::-1][:1] * 2,  # 通し番号が重複
        _icc_chunks(_ICC_PROFILE_300 + b"extra", [200, 105]),  # 合計長が申告長と不一致
        _icc_chunks(_ICC_PROFILE_300[:250], [250]),  # 申告長より短い（途中切れ）
        [_seg(0xE2, b"ICC_PROFILE\x00\x01\x01" + struct.pack(">I", 64) + bytes(60))],  # ヘッダ未満
    ],
    ids=["missing-chunk", "duplicate-sequence", "size-mismatch", "short", "tiny-header"],
)
def test_jpeg_inconsistent_icc_is_dropped(icc_segments: list[bytes]):
    """整合しない ICC は（ブラウザも使わないため）全チャンクを落とし、画像自体は受け付ける。"""
    original = _SOI + b"".join(icc_segments) + _JPEG_BODY
    assert strip_image_metadata(original, "jpeg") == _SOI + _JPEG_BODY


def _icc_profile_with(fragment: bytes, offset: int) -> bytes:
    """申告長 300 の ICC 本体の ``offset`` バイト目から ``fragment`` を書き込んだもの。"""
    profile = bytearray(_ICC_PROFILE_300)
    profile[offset : offset + len(fragment)] = fragment
    return bytes(profile)


_SIGNATURE_FRAGMENTS = pytest.mark.parametrize(
    "fragment",
    [b"II*\x00\x08\x00\x00\x00", b"MM\x00*\x00\x00\x00\x08", b"http://ns.adobe.com/"],
    ids=["tiff-le", "tiff-be", "xmp"],
)


@_SIGNATURE_FRAGMENTS
@pytest.mark.parametrize("file_order", ["in-order", "reversed"])
def test_jpeg_icc_signature_across_chunk_boundary_drops_icc(fragment: bytes, file_order: str):
    """L-3: 分割チャンクの境目をまたぐ Exif / XMP の目印も、デコーダと同じく通し番号順に
    つないだプロファイル全体で見つけて ICC を全部落とす（ICC の既存方針どおり、写真自体は
    受け付けて色が sRGB 扱いになるだけ）。ファイル上の並びが逆でも同じ。"""
    split_at = 200
    straddling_profile = _icc_profile_with(fragment, split_at - len(fragment) // 2)
    chunks = _icc_chunks(straddling_profile, [split_at, 100])
    clean_chunks = _icc_chunks(_ICC_PROFILE_300, [split_at, 100])
    # 各チャンク単体には目印の全体が入っていない（境目をまたいでいる）。
    assert all(fragment not in chunk for chunk in chunks)
    if file_order == "reversed":
        chunks, clean_chunks = chunks[::-1], clean_chunks[::-1]

    stripped = strip_image_metadata(_SOI + b"".join(chunks) + _JPEG_BODY, "jpeg")

    assert stripped == _SOI + _JPEG_BODY
    # 目印が無ければ同じ並びのまま残る（落としたのは目印のため）。
    clean = _SOI + b"".join(clean_chunks) + _JPEG_BODY
    assert strip_image_metadata(clean, "jpeg") == clean


@_SIGNATURE_FRAGMENTS
def test_jpeg_icc_signature_inside_one_chunk_drops_icc(fragment: bytes):
    """チャンク 1 個の中に収まる目印も同じく ICC を全部落とす（従来の挙動を固定）。"""
    chunks = _icc_chunks(_icc_profile_with(fragment, 250), [200, 100])
    stripped = strip_image_metadata(_SOI + b"".join(chunks) + _JPEG_BODY, "jpeg")
    assert stripped == _SOI + _JPEG_BODY


# ──────────────────────────── JPEG: fail closed ────────────────────────────


@pytest.mark.parametrize(
    "broken",
    [
        b"",
        b"\xff",
        b"\x00\xd8\xff\xe0",  # SOI 無し
        _CLEAN_PNG,  # 形式違い
        _SOI + b"\xff\xe1\xff\xff" + b"Exif\x00\x00short",  # SOS 前のセグメント途中で途切れ
        _SOI + _APP0_JFIF + b"\x00" * 16,  # 余分なバイトのまま終わる（画像データ無し）
        _SOI + _APP0_JFIF + _DQT + _EOI,  # SOS より前に EOI（画像データ無し）
        _SOI + _DQT + _SOF0 + _SOS_1[:-2],  # 最初の SOS ヘッダの途中で途切れ
        _SOI + b"\xff\xdb\x00\x01" + _JPEG_BODY,  # 残すセグメントの長さが 2 未満
        _SOI + _seg(0xDB, b"\x04" + bytes(64)) + _JPEG_BODY,  # DQT の表番号 4
        _SOI + _seg(0xDB, b"\x00" + bytes(63)) + _JPEG_BODY,  # DQT の表が途中で終わる
        _SOI + _seg(0xDB, b"\x20" + bytes(64)) + _JPEG_BODY,  # DQT の精度 2
        _SOI + _seg(0xC4, b"\x20" + bytes(16)) + _JPEG_BODY,  # DHT の表クラス 2
        _SOI + _seg(0xC4, _DHT[4:] + b"\x00") + _JPEG_BODY,  # DHT の後ろに余り
        _SOI + _seg(0xC4, b"\x00" + b"\x10" + bytes(15)) + _JPEG_BODY,  # 符号数が長さ超え
        _SOI + _seg(0xC0, _SOF0[4:] + b"\x00") + _JPEG_BODY,  # SOF の長さ不整合
        _SOI + _DQT + _SOF0 + _seg(0xDA, _SOS_1[4:] + b"\x00") + _ENTROPY_2 + _EOI,  # SOS
        _SOI + _seg(0xDD, b"\x00\x02\x00") + _JPEG_BODY,  # DRI の長さ不整合
        _SOI + _seg(0xCC, b"\x00") + _JPEG_BODY,  # DAC の長さが奇数
        _SOI + _seg(0xCC, b"\x20\x01") + _JPEG_BODY,  # DAC の表番号 32
    ],
    ids=[
        "empty", "one-byte", "no-soi", "png", "cut-before-sos", "only-junk-after-header",
        "eoi-before-sos", "cut-in-first-sos-header", "kept-length-below-2", "dqt-table-id",
        "dqt-partial-table", "dqt-precision", "dht-class", "dht-trailing-byte",
        "dht-count-over-length", "sof-length", "sos-length", "dri-length", "dac-odd", "dac-index",
    ],
)
def test_jpeg_broken_structure_raises(broken: bytes):
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "jpeg")


@pytest.mark.parametrize("marker", [0x02, 0xBF, 0xC8, 0xD8, 0xF0, 0xFD])
def test_jpeg_reserved_or_misplaced_marker_raises(marker: int):
    """予約マーカー・SOI の再出現は libjpeg も致命エラーにするため例外（0xFF00 は読み飛ばす）。"""
    broken = _SOI + bytes((0xFF, marker)) + b"\x00\x04\x00\x00" + _JPEG_BODY
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "jpeg")


def test_jpeg_segment_count_limit(monkeypatch):
    monkeypatch.setattr(image_metadata, "_MAX_JPEG_SEGMENTS", 8)
    # COM×4・DQT・SOF0・SOS・EOI でちょうど 8 セグメント。
    assert strip_image_metadata(_SOI + _COM * 4 + _JPEG_BODY, "jpeg") == _SOI + _JPEG_BODY
    with pytest.raises(ImageMetadataError, match="上限"):
        strip_image_metadata(_SOI + _COM * 5 + _JPEG_BODY, "jpeg")


def test_jpeg_table_count_limit(monkeypatch):
    monkeypatch.setattr(image_metadata, "_MAX_JPEG_TABLES", 2)
    two_tables = _SOI + _DQT + _SOF0 + _DHT + _SOS_1 + _ENTROPY_2 + _EOI
    assert strip_image_metadata(two_tables, "jpeg") == two_tables
    with pytest.raises(ImageMetadataError, match="上限"):
        strip_image_metadata(_insert_after(two_tables, _DHT, _DHT_2), "jpeg")


# ──────────────────────────── PNG ────────────────────────────


def test_png_strips_text_exif_time_and_trailer_keeping_other_chunks():
    original, expected = _png_with_metadata()
    stripped = strip_image_metadata(original, "png")

    assert stripped == expected
    for chunk_type in (b"tEXt", b"zTXt", b"iTXt", b"tIME", b"caBX", b"exIf"):
        assert chunk_type not in stripped
    # eXIf は向き（Orientation=6）だけを持つ最小形 1 個になり、GPS・Make は残らない。
    exif_chunks = [chunk for chunk in _png_chunks(stripped) if chunk[0] == b"eXIf"]
    assert [payload for _, payload, _ in exif_chunks] == [_minimal_tiff("<", 6)]
    assert b"SENTINEL" not in stripped
    assert _gps_bytes("<") not in stripped
    assert stripped.endswith(_IEND)


def test_png_without_metadata_passes_through_unchanged():
    assert strip_image_metadata(_CLEAN_PNG, "png") == _CLEAN_PNG


def _png_with_exif(*exif_chunks: bytes) -> bytes:
    """IHDR の直後に ``exif_chunks`` を置いた PNG（何も渡さなければ _CLEAN_PNG と同じ）。"""
    return _PNG_SIGNATURE + _IHDR + b"".join(exif_chunks) + _IDAT_1 + _IDAT_2 + _IEND


@_ENDIANS
@pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
def test_png_keeps_rotated_orientation_as_minimal_exif(endian: str, orientation: int):
    """eXIf の向き（2〜8）は、同じ位置に Orientation だけの最小の eXIf（CRC 正）として残る。"""
    original = _png_with_exif(_png_chunk(b"eXIf", _exif_tiff(endian, orientation=orientation)))
    stripped = strip_image_metadata(original, "png")

    assert stripped == _png_with_exif(_png_chunk(b"eXIf", _minimal_tiff(endian, orientation)))
    exif_chunks = [chunk for chunk in _png_chunks(stripped) if chunk[0] == b"eXIf"]
    assert len(exif_chunks) == 1
    _, payload, crc = exif_chunks[0]
    assert payload == _minimal_tiff(endian, orientation)
    assert crc == zlib.crc32(b"eXIf" + payload)
    assert _gps_bytes(endian) not in stripped
    assert b"SENTINEL" not in stripped


@_ENDIANS
@pytest.mark.parametrize("orientation", [None, 0, 1, 9, 0xFFFF])
def test_png_drops_exif_entirely_when_orientation_is_upright_or_invalid(
    endian: str, orientation: int | None
):
    original = _png_with_exif(_png_chunk(b"eXIf", _exif_tiff(endian, orientation=orientation)))
    stripped = strip_image_metadata(original, "png")
    assert stripped == _CLEAN_PNG
    assert b"eXIf" not in stripped


@pytest.mark.parametrize(
    "exif_data",
    [
        b"",
        b"II\x2a\x00\x08\x00",  # TIFF ヘッダの途中で切れ
        b"Exif\x00\x00" + _minimal_tiff("<", 6),  # JPEG の APP1 形式（PNG の eXIf には付けない）
        b"XX" + _minimal_tiff("<", 6)[2:],  # バイト順が不正
        _minimal_tiff("<", 6)[:-10],  # エントリの途中で切れ
    ],
    ids=["empty", "short-header", "jpeg-style-prefix", "bad-byte-order", "truncated-ifd"],
)
def test_png_drops_unreadable_exif_without_error(exif_data: bytes):
    """読めない eXIf は丸ごと捨てて成功する（向きは正立扱い）。"""
    original = _png_with_exif(_png_chunk(b"eXIf", exif_data))
    assert strip_image_metadata(original, "png") == _CLEAN_PNG


def test_png_orientation_comes_from_first_exif_only():
    """eXIf は仕様上 1 個まで（libpng も 2 個目以降を無視する）。2 個目以降は向きがあっても
    読まずに落とし、最小の eXIf は 1 個目の位置に置く。"""
    upright_first = _png_with_exif(
        _png_chunk(b"eXIf", _exif_tiff("<", orientation=None)),
        _png_chunk(b"eXIf", _exif_tiff("<", orientation=6)),
    )
    assert strip_image_metadata(upright_first, "png") == _CLEAN_PNG

    rotated_twice = _png_with_exif(
        _png_chunk(b"eXIf", _exif_tiff(">", orientation=3)),
        _png_chunk(b"eXIf", _exif_tiff("<", orientation=6)),
    )
    expected = _png_with_exif(_png_chunk(b"eXIf", _minimal_tiff(">", 3)))
    assert strip_image_metadata(rotated_twice, "png") == expected

    # IDAT の後ろにある eXIf も、その位置のまま置き直す（表示側の扱いを変えない）。
    after_idat = _CLEAN_PNG[: -len(_IEND)] + _png_chunk(b"eXIf", _exif_tiff("<", orientation=8))
    expected_after_idat = _CLEAN_PNG[: -len(_IEND)] + _png_chunk(b"eXIf", _minimal_tiff("<", 8))
    assert strip_image_metadata(after_idat + _IEND, "png") == expected_after_idat + _IEND


@pytest.mark.parametrize(
    ("chunk_type", "kept"),
    [
        (b"acTL", True),  # APNG
        (b"fcTL", True),
        (b"fdAT", True),
        (b"cICP", True),  # HDR
        (b"bKGD", True),
        (b"PLTE", True),  # 必須チャンク
        (b"ZZZZ", True),  # 未知の必須チャンク（落とすと画像が壊れるため残す）
        (b"iDOT", False),  # アプリ独自の補助チャンク
        (b"prVt", False),
        (b"dSIG", False),
    ],
)
def test_png_chunk_allowlist(chunk_type: bytes, kept: bool):
    chunk = _png_chunk(chunk_type, b"\x00\x01\x02")
    original = _PNG_SIGNATURE + _IHDR + chunk + _IDAT_1 + _IDAT_2 + _IEND
    expected = _PNG_SIGNATURE + _IHDR + (chunk if kept else b"") + _IDAT_1 + _IDAT_2 + _IEND
    assert strip_image_metadata(original, "png") == expected


def test_png_iend_with_payload_is_normalized():
    original = _PNG_SIGNATURE + _IHDR + _IDAT_1 + _IDAT_2 + _png_chunk(b"IEND", b"SENTINEL")
    assert strip_image_metadata(original, "png") == _CLEAN_PNG


@pytest.mark.parametrize(
    "broken",
    [
        b"\x89PNG\r\n\x1a",  # シグネチャ途中
        _CLEAN_PNG[:-12],  # IEND 無し
        _PNG_SIGNATURE + struct.pack(">I", 1000) + b"IDAT" + b"\x00" * 10,  # 申告長が長すぎる
        _PNG_SIGNATURE + struct.pack(">I", 0x8000_0000) + b"IDAT",  # 仕様上限超え
        _PNG_SIGNATURE + _IHDR + b"\x00\x00\x00\x00ID@T\x00\x00\x00\x00" + _IEND,  # 種別が不正
        _PNG_SIGNATURE + _IHDR[:-1] + _IDAT_1 + _IEND,  # 1 バイト欠けて境界がずれる
    ],
    ids=[
        "short-signature", "no-iend", "length-too-long", "length-over-spec", "bad-type",
        "shifted",
    ],
)
def test_png_broken_structure_raises(broken: bytes):
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "png")


def test_png_chunk_count_limit(monkeypatch):
    monkeypatch.setattr(image_metadata, "_MAX_PNG_CHUNKS", 4)
    assert strip_image_metadata(_CLEAN_PNG, "png") == _CLEAN_PNG  # IHDR・IDAT×2・IEND
    with pytest.raises(ImageMetadataError, match="上限"):
        strip_image_metadata(_PNG_SIGNATURE + _IHDR + _IDAT_1 + _IDAT_1 + _IDAT_2 + _IEND, "png")


# ──────────────────────────── WebP ────────────────────────────


def test_webp_strips_exif_xmp_unknown_chunks_and_fixes_header():
    original, expected = _webp_with_metadata()
    stripped = strip_image_metadata(original, "webp")

    assert stripped == expected
    assert b"XMP " not in stripped and b"C2PA" not in stripped
    # EXIF は向き（Orientation=6）だけを持つ最小形 1 個になり、GPS・Make は残らない。
    assert stripped.count(b"EXIF") == 1
    assert stripped.endswith(_webp_chunk(b"EXIF", _minimal_tiff("<", 6)))
    assert b"SENTINEL" not in stripped
    assert _gps_bytes("<") not in stripped
    (riff_size,) = struct.unpack_from("<I", stripped, 4)
    assert riff_size == len(stripped) - 8
    vp8x_flags = stripped[20]  # RIFF ヘッダ 12 + VP8X チャンクヘッダ 8
    assert vp8x_flags == _WEBP_FLAG_ICC | _WEBP_FLAG_ALPHA | _WEBP_FLAG_EXIF


def test_webp_without_metadata_passes_through_unchanged():
    assert strip_image_metadata(_CLEAN_WEBP, "webp") == _CLEAN_WEBP


def _webp_exif(endian: str, orientation: int | None) -> bytes:
    """GPS 付きの EXIF チャンク（データは TIFF ヘッダから始まる）。"""
    return _webp_chunk(b"EXIF", _exif_tiff(endian, orientation=orientation))


@_ENDIANS
@pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
def test_webp_keeps_rotated_orientation_as_minimal_exif(endian: str, orientation: int):
    """先頭が VP8X の WebP は、EXIF の向き（2〜8）を同じ位置の最小の EXIF として残し、
    VP8X の EXIF フラグ（0x08）を立て直す（XMP フラグは落としたまま）。"""
    xmp = _webp_chunk(b"XMP ", b"<x:xmpmeta>SENTINEL-WEBP-XMP</x:xmpmeta>")
    original = _riff_webp(
        _vp8x(_WEBP_FLAG_ALPHA | _WEBP_FLAG_EXIF | _WEBP_FLAG_XMP)
        + _WEBP_ALPH
        + _WEBP_VP8
        + _webp_exif(endian, orientation)
        + xmp
    )
    stripped = strip_image_metadata(original, "webp")

    minimal_exif = _webp_chunk(b"EXIF", _minimal_tiff(endian, orientation))
    assert len(minimal_exif) == 8 + 26  # 偶数長（パディング不要）
    assert stripped == _riff_webp(
        _vp8x(_WEBP_FLAG_ALPHA | _WEBP_FLAG_EXIF) + _WEBP_ALPH + _WEBP_VP8 + minimal_exif
    )
    (riff_size,) = struct.unpack_from("<I", stripped, 4)
    assert riff_size == len(stripped) - 8
    assert stripped[20] & _WEBP_FLAG_EXIF
    assert _gps_bytes(endian) not in stripped
    assert b"SENTINEL" not in stripped


@_ENDIANS
@pytest.mark.parametrize("orientation", [None, 0, 1, 9, 0xFFFF])
def test_webp_drops_exif_entirely_when_orientation_is_upright_or_invalid(
    endian: str, orientation: int | None
):
    original = _riff_webp(_vp8x(_WEBP_FLAG_EXIF) + _WEBP_VP8 + _webp_exif(endian, orientation))
    stripped = strip_image_metadata(original, "webp")
    assert stripped == _riff_webp(_vp8x(0) + _WEBP_VP8)
    assert b"EXIF" not in stripped


@pytest.mark.parametrize(
    ("body", "expected_body"),
    [
        # 単純形式（VP8X なし）: デコーダはメタデータのチャンクを読まない。
        (_WEBP_VP8 + _webp_exif("<", 6), _WEBP_VP8),
        # VP8X が先頭にない（拡張形式として扱われない）。
        (_WEBP_VP8 + _vp8x(_WEBP_FLAG_EXIF) + _webp_exif(">", 6), _WEBP_VP8 + _vp8x(0)),
    ],
    ids=["no-vp8x", "vp8x-not-first"],
)
def test_webp_without_leading_vp8x_drops_orientation(body: bytes, expected_body: bytes):
    stripped = strip_image_metadata(_riff_webp(body), "webp")
    assert stripped == _riff_webp(expected_body)
    assert b"EXIF" not in stripped
    (riff_size,) = struct.unpack_from("<I", stripped, 4)
    assert riff_size == len(stripped) - 8


@pytest.mark.parametrize(
    "exif_chunks",
    [
        # EXIF は 1 個まで（コンテナ仕様: 読み手は 2 個目以降を無視してよい）。
        _webp_exif("<", None) + _webp_exif("<", 6),
        # JPEG の APP1 形式（"Exif\0\0" 付き）は TIFF として読めないため捨てる。
        _webp_chunk(b"EXIF", b"Exif\x00\x00" + _minimal_tiff("<", 6)),
    ],
    ids=["second-exif-ignored", "jpeg-style-prefix"],
)
def test_webp_drops_exif_without_readable_orientation_in_first_chunk(exif_chunks: bytes):
    original = _riff_webp(_vp8x(_WEBP_FLAG_EXIF) + _WEBP_VP8 + exif_chunks)
    assert strip_image_metadata(original, "webp") == _riff_webp(_vp8x(0) + _WEBP_VP8)


def test_webp_accepts_missing_final_padding_and_normalizes_it():
    """最後の奇数長チャンクだけパディングが欠けた入力は、補って正しい RIFF にする。"""
    unpadded_vp8 = _WEBP_VP8[:-1]
    body = _vp8x(_WEBP_FLAG_EXIF) + unpadded_vp8
    original = b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body
    assert strip_image_metadata(original, "webp") == _riff_webp(_vp8x(0) + _WEBP_VP8)


@pytest.mark.parametrize(
    "broken",
    [
        b"RIFF\x04\x00\x00\x00WEB",  # ヘッダ途中
        b"RIFX" + _CLEAN_WEBP[4:],  # RIFF でない
        b"RIFF" + struct.pack("<I", len(_CLEAN_WEBP)) + _CLEAN_WEBP[8:],  # RIFF サイズが長すぎる
        b"RIFF" + struct.pack("<I", 3) + b"WEBP",  # RIFF サイズが短すぎる
        _riff_webp(b"VP8 " + struct.pack("<I", 100) + b"\x00" * 10),  # チャンク長が RIFF 超え
        _riff_webp(_webp_chunk(b"VP8X", b"\x08\x00\x00\x00")),  # VP8X が 10 バイトでない
        _riff_webp(_WEBP_VP8 + b"\x00\x00\x00"),  # チャンクヘッダ途中で RIFF 終端
    ],
    ids=["short-header", "not-riff", "riff-too-long", "riff-too-short", "chunk-too-long",
         "bad-vp8x", "partial-chunk-header"],
)
def test_webp_broken_structure_raises(broken: bytes):
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(broken, "webp")


def test_webp_chunk_count_limit(monkeypatch):
    monkeypatch.setattr(image_metadata, "_MAX_WEBP_CHUNKS", 2)
    assert strip_image_metadata(_riff_webp(_vp8x(0) + _WEBP_VP8), "webp")
    with pytest.raises(ImageMetadataError, match="上限"):
        strip_image_metadata(_riff_webp(_vp8x(0) + _WEBP_ICCP + _WEBP_VP8), "webp")


# ──────────────────────────── 形式共通の性質 ────────────────────────────


@pytest.mark.parametrize("ext", ["gif", "heic", "bmp", ""])
def test_unsupported_format_raises(ext: str):
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(_CLEAN_JPEG, ext)


@pytest.mark.parametrize("ext", ["png", "webp"])
def test_png_and_webp_every_truncation_raises(ext: str):
    """PNG / WebP は完全な画像をどこで切っても ImageMetadataError（途中切れは fail closed）。"""
    complete, _ = _SAMPLES[ext](trailer=False)
    for cut in range(len(complete)):
        with pytest.raises(ImageMetadataError):
            strip_image_metadata(complete[:cut], ext)


@_FORMATS
def test_output_is_idempotent(ext: str):
    """配信時に毎回通しても結果が変わらない（保存済みの除去後データを再度通す経路の前提）。"""
    original, expected = _SAMPLES[ext]()
    assert strip_image_metadata(expected, ext) == expected
    assert strip_image_metadata(strip_image_metadata(original, ext), ext) == expected


@_FORMATS
def test_mutated_inputs_only_raise_image_metadata_error(ext: str):
    """ランダムに壊した入力でも IndexError / struct.error 等は漏れず、成功時の出力は冪等。

    想定外の例外は配信で 500（= 5xx 通知）になり、失敗が ImageMetadataError に揃って
    いることが fail closed の前提になる。JPEG は破損を受け付ける範囲が広い（QA M1）ため、
    成功時に EOI で終わりメタデータ（目印・GPS）が一切残らないことも確かめる。
    """
    original, _ = _SAMPLES[ext]()
    rng = random.Random(20260924)
    for _ in range(1500):
        mutated = bytearray(original)
        operation = rng.random()
        if operation < 0.6:
            for _ in range(rng.randint(1, 4)):
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        elif operation < 0.8:
            start = rng.randrange(len(mutated))
            del mutated[start : start + rng.randint(1, 16)]
        else:
            mutated[rng.randrange(len(mutated)) : 0] = rng.randbytes(rng.randint(1, 16))
        try:
            stripped = strip_image_metadata(bytes(mutated), ext)
        except ImageMetadataError:
            continue
        assert strip_image_metadata(stripped, ext) == stripped
        if ext == "jpeg":
            assert stripped.endswith(_EOI)
            assert b"SENTINEL" not in stripped
            assert _gps_bytes("<") not in stripped


@pytest.mark.parametrize(
    "swallowed",
    [
        # IFD0 のオフセットが 8 以外の Exif（TIFF ヘッダの目印には一致しない）。
        b"Exif\x00\x00II*\x00\x10\x00\x00\x00" + bytes(8) + b"GPS-FRAGMENT",
        # 市区町村名などを持つ IPTC（APP13）。
        b"Photoshop 3.0\x008BIM\x04\x04\x00\x00\x00\x00\x00\x12CITY-FRAGMENT",
    ],
    ids=["exif_ifd0_offset_16", "photoshop_iptc"],
)
def test_signature_check_detects_swallowed_exif_and_iptc_identifiers(swallowed: bytes):
    """壊れたファイルでスキャンデータに吸収された Exif（IFD0 オフセットを問わない）・IPTC の
    識別子も目印として検出し、除去を保証できないものとして拒否する（security review Low）。"""
    data = _SOI + _APP0_JFIF + _DQT + _SOF0 + _SOS_1 + b"\x12\x34" + swallowed + _EOI
    with pytest.raises(ImageMetadataError):
        strip_image_metadata(data, "jpeg")


def test_orientation_probe_is_bounded_for_many_huge_exif_segments(monkeypatch):
    """向き探しは先頭の Exif APP1 数個・IFD0 の先頭 1024 件までに限る（無認証配信の計算量対策）。

    エントリ数 0xFFFF を宣言して中身を 0 で埋めた（向きを持たない）Exif APP1 を大量に並べる
    細工入力で、Python のループが数十万回回らないこと。APP1 自体は従来どおり全部落とす。
    """
    calls: list[int] = []
    original = image_metadata._read_exif_orientation

    def spy(payload: bytes):
        calls.append(len(payload))
        return original(payload)

    monkeypatch.setattr(image_metadata, "_read_exif_orientation", spy)
    huge_tiff = b"II" + struct.pack("<HI", 42, 8) + struct.pack("<H", 0xFFFF) + bytes(60_000)
    huge_app1 = _seg(0xE1, b"Exif\x00\x00" + huge_tiff)
    data = _SOI + _APP0_JFIF + huge_app1 * 10 + _JPEG_BODY

    out = strip_image_metadata(data, "jpeg")

    assert len(calls) == image_metadata._MAX_EXIF_ORIENTATION_PROBES
    assert b"Exif" not in out
    assert out == _SOI + _APP0_JFIF + _JPEG_BODY


# ──────────────────────────── エンドポイント ────────────────────────────

_CONTENT_TYPES = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_KEY_EXTENSIONS = {"jpeg": "jpg", "png": "png", "webp": "webp"}
# 最初の SOS より前（GPS 付き Exif の直後の XMP の途中）で途切れた JPEG。除去を保証できない。
_JPEG_CUT_BEFORE_SCAN = _jpeg_with_metadata("<", trailer=False)[0][
    : len(_SOI + _APP0_JFIF + _EXIF_II_6) + 30
]


async def _presign(client: AsyncClient, token: str, content_type: str) -> dict:
    r = await client.post(
        "/api/v1/upload/presign",
        json={"filename": "room", "content_type": content_type},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    return r.json()


@_FORMATS
async def test_upload_saves_only_stripped_bytes(
    client: AsyncClient, db_session: AsyncSession, tmp_storage, ext: str
):
    """① GPS 付きの写真をアップロードしても、保存される実体と配信内容に GPS が無い。"""
    token = await _make_user_token(db_session)
    presign = await _presign(client, token, _CONTENT_TYPES[ext])
    original, expected = _SAMPLES[ext]()

    r = await client.put(
        presign["upload_url"],
        content=original,
        headers={**_auth(token), "Content-Type": _CONTENT_TYPES[ext]},
    )
    assert r.status_code == 204, r.text

    saved = (tmp_storage / presign["storage_key"]).read_bytes()
    assert saved == expected
    assert _gps_bytes("<") not in saved
    assert b"SENTINEL" not in saved

    r = await client.get(presign["public_url"])
    assert r.status_code == 200
    assert r.content == expected


async def test_upload_accepts_jpeg_with_tolerated_corruption(
    client: AsyncClient, db_session: AsyncSession, tmp_storage
):
    """QA M1: ブラウザが表示できる程度に壊れた原本（EOI 欠落・余分なバイト等）も 204 で、
    保存されるのは除去後の整ったバイト列。"""
    token = await _make_user_token(db_session)
    presign = await _presign(client, token, "image/jpeg")
    complete, expected = _jpeg_with_metadata("<", trailer=False)

    r = await client.put(
        presign["upload_url"],
        content=_all_corruptions(complete),
        headers={**_auth(token), "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 204, r.text
    assert (tmp_storage / presign["storage_key"]).read_bytes() == expected


@_FORMATS
async def test_serve_file_strips_previously_saved_photo(
    client: AsyncClient, tmp_storage, ext: str
):
    """② 対策以前に GPS 付きのまま保存された写真も、配信時に除去される（実体は書き換えない）。"""
    storage_key = f"{uuid.uuid4().hex}.{_KEY_EXTENSIONS[ext]}"
    original, expected = _SAMPLES[ext]()
    (tmp_storage / storage_key).write_bytes(original)

    r = await client.get(f"/api/v1/files/{storage_key}")
    assert r.status_code == 200
    assert r.content == expected
    assert b"SENTINEL" not in r.content
    # Content-Type・キャッシュヘッダーは従来どおり。
    assert r.headers["content-type"] == _CONTENT_TYPES[ext]
    assert r.headers["ETag"] == f'"{storage_key}"'
    assert r.headers["Cache-Control"] == "private, no-cache"
    assert r.headers["Vary"] == "Authorization"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert (tmp_storage / storage_key).read_bytes() == original


async def test_serve_file_delivers_previously_saved_jpeg_with_tolerated_corruption(
    client: AsyncClient, tmp_storage
):
    """QA M1: 軽微に壊れた既存の保存写真も 404 にせず、除去して配信する。"""
    storage_key = f"{uuid.uuid4().hex}.jpg"
    complete, expected = _jpeg_with_metadata("<", trailer=False)
    (tmp_storage / storage_key).write_bytes(_all_corruptions(complete))

    r = await client.get(f"/api/v1/files/{storage_key}")
    assert r.status_code == 200
    assert r.content == expected


async def test_serve_file_uses_sniffed_format_not_key_extension(
    client: AsyncClient, tmp_storage
):
    """web は形式不明の写真を image/jpeg で presign するため、.jpg の実体が PNG でも除去できる。"""
    storage_key = f"{uuid.uuid4().hex}.jpg"
    original, expected = _png_with_metadata()
    (tmp_storage / storage_key).write_bytes(original)

    r = await client.get(f"/api/v1/files/{storage_key}")
    assert r.status_code == 200
    assert r.content == expected


async def test_upload_rejects_broken_jpeg_with_415_and_saves_nothing(
    client: AsyncClient, db_session: AsyncSession, tmp_storage
):
    """③ シグネチャは JPEG でも画像データより前で途切れていれば、非対応形式と同じ 415 で
    何も保存しない。"""
    token = await _make_user_token(db_session)
    presign = await _presign(client, token, "image/jpeg")

    r = await client.put(
        presign["upload_url"],
        content=_JPEG_CUT_BEFORE_SCAN,
        headers={**_auth(token), "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 415
    assert "対応していません" in r.json()["detail"]
    assert not (tmp_storage / presign["storage_key"]).exists()


@pytest.mark.parametrize(
    "stored",
    [_JPEG_CUT_BEFORE_SCAN, b"dummy-jpeg-bytes"],
    ids=["jpeg-cut-before-scan-with-gps", "not-an-image"],
)
async def test_serve_file_fails_closed_when_metadata_cannot_be_stripped(
    client: AsyncClient, tmp_storage, caplog, stored: bytes
):
    """除去できない保存済みファイルは元のバイト列を返さず 404（5xx 通知も鳴らさない）。"""
    storage_key = f"{uuid.uuid4().hex}.jpg"
    (tmp_storage / storage_key).write_bytes(stored)
    caplog.set_level(logging.WARNING, logger="app.api.v1.endpoints.case_photos")

    r = await client.get(f"/api/v1/files/{storage_key}")
    assert r.status_code == 404
    assert _gps_bytes("<") not in r.content
    assert stored not in r.content

    messages = [
        record.getMessage() for record in caplog.records if "serve_file" in record.getMessage()
    ]
    assert len(messages) == 1
    # ログの storage_key は既存方針（mask_key_for_log）どおり先頭 8 文字に丸める。
    assert f"key={storage_key[:8]}..." in messages[0]
    assert storage_key not in messages[0]
    assert "累計" in messages[0]


async def test_serve_file_strip_failure_log_is_throttled(
    client: AsyncClient, tmp_storage, caplog
):
    """壊れた写真が繰り返し閲覧されても、warning は間引かれて 1 行だけになる。"""
    caplog.set_level(logging.WARNING, logger="app.api.v1.endpoints.case_photos")
    for _ in range(3):
        storage_key = f"{uuid.uuid4().hex}.jpg"
        (tmp_storage / storage_key).write_bytes(_JPEG_CUT_BEFORE_SCAN)
        assert (await client.get(f"/api/v1/files/{storage_key}")).status_code == 404

    messages = [
        record.getMessage() for record in caplog.records if "serve_file" in record.getMessage()
    ]
    assert len(messages) == 1


async def test_serve_file_if_none_match_still_returns_304_without_reading_body(
    client: AsyncClient, tmp_storage
):
    """304 経路は本体を返さないため除去を通さない（キャッシュ挙動は従来どおり）。"""
    storage_key = f"{uuid.uuid4().hex}.jpg"
    original, _ = _jpeg_with_metadata("<")
    (tmp_storage / storage_key).write_bytes(original)

    r = await client.get(
        f"/api/v1/files/{storage_key}", headers={"If-None-Match": f'"{storage_key}"'}
    )
    assert r.status_code == 304
    assert r.content == b""
