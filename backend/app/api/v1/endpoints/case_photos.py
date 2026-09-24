"""写真アップロード — presign（疑似署名）/ PUT 本体 / GET 配信。

保存先は STORAGE_BACKEND に応じてローカルディスク / Cloudflare R2 を切り替える
（services/storage.py）。R2 が有効な場合はデプロイをまたいで永続化される。
presign はユーザー認証必須。アップロード本体（PUT）も認証必須にする
（security review 指摘対応: storage_key の推測不能性のみに依存した
capability URL 方式は、アルバム化でstorage_keyの露出面（案件一覧・
入札一覧等のレスポンスに含まれる箇所）が増えたことで優先度が上がった）。

security review 確定指摘（MEDIUM）対応: 写真を EXIF 付きのまま保存・配信していた
ため、承認済み業者が成約前に依頼者の自宅の GPS 座標を取得できた。受信（PUT）で
メタデータを除去してから保存し、配信（GET）でも同じ除去を通す（対策以前に保存
済みの写真を、本番データを書き換えずに塞ぐため）。除去は画素を再エンコードしない
（services/image_metadata.py）。
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import (
    OPERATOR_APPROVAL_REQUIRED_DETAIL,
    OPERATOR_CASE_VIEW_STATUSES,
    SUSPENDED_ACCOUNT_DETAIL,
    get_current_user,
    get_optional_operator,
)
from app.core.log_throttle import ThrottledLogger
from app.db.models.operator import Operator
from app.db.models.user import User
from app.schemas_katadzuke import PresignRequest, PresignResponse
from app.services import storage
from app.services.image_metadata import ImageMetadataError, strip_image_metadata
from app.services.storage import MAX_UPLOAD_BYTES, StorageKeyConflictError, StorageUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter()

# メタデータ除去の失敗ログは間引く（壊れた1枚が閲覧・再送のたびにログを埋めないように。
# 警告の種類ごとに別インスタンス: core/log_throttle.py の方針）。間引いた分もプロセス内
# 累計件数として次に出る行に含める（deps.py の X-Ops-Token 不一致と同じ流儀）。
_upload_strip_failure_throttle = ThrottledLogger()
_serve_strip_failure_throttle = ThrottledLogger()
_upload_strip_failure_count = 0
_serve_strip_failure_count = 0


def _note_upload_strip_failure(user_id: object, image_ext: str, reason: Exception) -> None:
    """受信時の除去失敗（415）を数え、間引いて warning を出す（未検証の key は出さない）。"""
    global _upload_strip_failure_count
    _upload_strip_failure_count += 1
    failure_count = _upload_strip_failure_count
    _upload_strip_failure_throttle.emit(
        lambda: logger.warning(
            "case_photos.upload: 画像の構造を解釈できずメタデータを除去できないため拒否 - "
            "user_id=%s ext=%s reason=%s（プロセス内累計 %s 件）",
            user_id,
            image_ext,
            reason,
            failure_count,
        )
    )


def _note_serve_strip_failure(storage_key: str, reason: Exception) -> None:
    """配信時の除去失敗（404）を数え、間引いて warning を出す（storage_key はマスクする）。"""
    global _serve_strip_failure_count
    _serve_strip_failure_count += 1
    failure_count = _serve_strip_failure_count
    masked_key = storage.mask_key_for_log(storage_key)
    _serve_strip_failure_throttle.emit(
        lambda: logger.warning(
            "case_photos.serve_file: メタデータを除去できないため配信を拒否（fail closed） - "
            "key=%s reason=%s（プロセス内累計 %s 件）",
            masked_key,
            reason,
            failure_count,
        )
    )

# Content-Lengthヘッダの申告値に対する早期拒否の許容量。ヘッダ自体が無い・
# 偽装されている場合は後続のストリーミング読み込みでのハード上限で捕捉する
# （operator_license.pyの許可証画像アップロードと同じ多重防御パターン）。
_MAX_DECLARED_CONTENT_LENGTH = MAX_UPLOAD_BYTES + 64 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
_TOO_LARGE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="ファイルサイズが上限（10MB）を超えています。写真を縮小するか、別の写真をお試しください。",
)
# 非対応形式の 415。web は detail をそのまま表示する契約のため、実際に多い失敗
# （iPhone の HEIC を「すべてのファイル」で選択して accept を回避した場合）に
# 次の行動が分かる文言にする（r8-H4）。判定は storage.sniff_image_ext の
# マジックバイト方式（jpeg/png/webp のみ）と1対1で対応させること。
# シグネチャは正しいが構造が壊れていてメタデータを除去できない画像（途中切れ・
# 長さ不整合）も同じ 415 にする（除去を保証できない画像は保存しない）。
_UNSUPPORTED_IMAGE = HTTPException(
    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    detail=(
        "この形式の画像には対応していません。"
        "JPEG・PNG・WebP のいずれかでアップロードしてください"
        "（iPhone の HEIC 形式は「設定 > カメラ > フォーマット > 互換性優先」で"
        "JPEG として保存できます）。"
    ),
)
_UPLOAD_STORAGE_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="写真の保存先に接続できませんでした。しばらくしてからもう一度お試しください。",
)
_SERVE_STORAGE_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="写真を取得できませんでした。しばらくしてからもう一度お試しください。",
)
_FILE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="ファイルが見つかりません。"
)


@router.post(
    "/upload/presign",
    response_model=PresignResponse,
    summary="写真アップロード URL の発行",
)
async def presign(
    body: PresignRequest,
    user: User = Depends(get_current_user),
) -> PresignResponse:
    try:
        key = storage.new_storage_key(body.content_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return PresignResponse(
        storage_key=key,
        upload_url=storage.upload_url(key),
        public_url=storage.public_url(key),
    )


@router.put(
    "/upload/{storage_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="写真本体のアップロード（認証必須）",
)
async def upload(
    storage_key: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    # 認証（Depends）は本関数の呼び出し前に解決済みのため、未認証のまま巨大
    # ボディを読み込む経路は無い。ただし認証済みユーザーが巨大なボディを送信
    # した場合のメモリDoSは別問題として残るため、Content-Lengthヘッダによる
    # 早期拒否＋ストリーミング読み込みでのハード上限を適用する
    # （security review 指摘対応。operator_license.pyと同じ多重防御パターン）。
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > _MAX_DECLARED_CONTENT_LENGTH:
            raise _TOO_LARGE

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise _TOO_LARGE
        chunks.append(chunk)
    data = b"".join(chunks)

    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ファイルが空です。写真を選び直してお試しください。",
        )
    # Content-Type ヘッダ・拡張子は詐称可能なため信用せず、実バイト列の先頭
    # シグネチャ（マジックバイト）で画像形式を判定する（security review 指摘対応。
    # operator_license.py の許可証画像アップロードと同じ方式に統一する）。
    image_ext = storage.sniff_image_ext(data)
    if image_ext is None:
        raise _UNSUPPORTED_IMAGE
    # 位置情報（EXIF の GPS 等）を含むメタデータを保存前に除去する（security review
    # 確定指摘・MEDIUM 対応）。web の「既存案件への写真追加」等は元ファイルをそのまま
    # 送るため、サーバ側での除去を正本とする。形式は拡張子ではなく上の sniff 結果で
    # 決める。数 MB の写真で数 ms の CPU 処理のため、イベントループを塞がないよう
    # スレッドへ逃がす。除去できない画像は元のバイト列を保存せず 415 で拒否する。
    try:
        sanitized_data = await asyncio.to_thread(strip_image_metadata, data, image_ext)
    except ImageMetadataError as exc:
        _note_upload_strip_failure(user.id, image_ext, exc)
        raise _UNSUPPORTED_IMAGE from exc
    try:
        await storage.save_bytes(storage_key, sanitized_data)
    except StorageKeyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except StorageUnavailableError as exc:
        raise _UPLOAD_STORAGE_UNAVAILABLE from exc


def _if_none_match_matches(header_value: str, etag: str) -> bool:
    """If-None-Match ヘッダを寛容にパースし、``etag`` と一致するか判定する。

    カンマ区切りの複数値・前後空白・弱いバリデータ接頭辞（``W/``）を許容する
    （RFC 7232 準拠のブラウザ実装差異を吸収するため）。``"*"`` は常に一致とみなす。
    """
    for raw_candidate in header_value.split(","):
        candidate = raw_candidate.strip()
        if not candidate:
            continue
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate == etag:
            return True
    return False


@router.get("/files/{storage_key}", summary="写真の配信", response_class=Response)
async def serve_file(
    storage_key: str,
    request: Request,
    operator: Operator | None = Depends(get_optional_operator),
) -> Response:
    """保存済み画像を配信する（従来どおり無認証の capability URL）。

    r12 決定1 の多層防御: 未承認・停止中の業者が **自分の業者トークンを付けて**
    画像を取得することを禁じる。一次防御はあくまで
    ``GET /cases`` / ``GET /cases/{id}`` の 403（未承認業者は storage_key 自体を
    受け取れない）であり、ここは「以前見えていた URL を控えていた」「他経路で
    storage_key を得た」場合の残余リスクを削るための二次防御。

    r12-review L-1: 判定に「その key が案件写真かどうか」を混ぜない。混ぜると
    403（案件写真である）／404・200（そうでない）の差が、未承認業者にとって
    **任意の storage_key が案件写真かを判別できるオラクル**になる。トークンを
    付けている以上その業者は未承認だと分かっているので、key の素性に関わらず
    一律 403 にするのが素直（正規の閲覧経路は承認後にトークン無しの ``<img>``
    ／承認済みトークンで従来どおり通る）。副次的に DB クエリも不要になり、
    この経路は完全に O(1)（無トークンの ``<img>``・依頼者・承認済み業者も
    従来どおり DB を一切引かない）。

    R2 移行に伴い、If-None-Match が一致する場合は本体を一切取得せず 304 を
    返す（R2 への到達自体が発生しない。キャッシュヒット時のコスト・レイテンシ
    削減）。storage_key は不変（毎回新規UUID）のためキー自体をそのまま強い
    ETag として使ってよい。

    security review 指摘対応（2回目レビュー Medium）: ``exists()``（R2 では
    HEAD）は 304 を返そうとする分岐（If-None-Match が一致した場合）でのみ
    呼び出し、200 を返す経路では呼ばない。200 経路は ``read_bytes()``
    （R2 では GET）の結果だけで「存在しない → 404」判定が完結するため、
    その手前で ``exists()`` を呼ぶと 200 応答のたびに R2 へ HEAD → GET の
    2 オペレーションが発生してしまう。本エンドポイントは無認証・
    レート制限無しの capability URL のため、形式だけ正しいランダムキーを
    大量に送られると HEAD がセマフォなしで無制限に発生し
    （``asyncio.to_thread`` の共有スレッドプールを飽和させ、AI 解析等の
    他処理を遅延させ得る）不要な負荷源になる。そのため R2 への到達は
    どの経路でも最大 1 回（304 経路は ``exists()`` のみ・200 経路は
    ``read_bytes()`` のみ）に抑える。

    security/qa review 指摘対応（1回目レビュー）: 304 分岐は ETag
    （＝ storage_key そのもの）が一致するかどうかしか見ないため、検証
    （形式）より前に置くと「一度もアップロードされていない・形式すら
    不正なキー」でも If-None-Match を偽装するだけで 304 が返ってしまう
    （実在確認・404 を完全にバイパスするオラクル）。そのため 304 判定は
    形式検証（``is_valid_key``）の**後**に置く。
    処理順序: ①業者403多層防御 → ②is_valid_key（不正なら404）→
    ③If-None-Match が一致する場合のみ exists() で実在確認
    （存在しなければ404、存在すれば304）→ ④（③に該当しない場合）
    read_bytes で本体取得し、None なら404 → ⑤メタデータ除去（失敗なら404）→ 200。

    security review 確定指摘（MEDIUM）対応（⑤）: 対策以前に EXIF 付きのまま保存
    された写真から GPS 座標を取得できないよう、返す直前にも受信時と同じ除去を通す
    （R2 は上書き不可のため本番データは書き換えない）。形式は storage_key の拡張子
    ではなく実バイトのシグネチャで決める（web はブラウザが形式を判定できない写真を
    image/jpeg として presign するため、拡張子 .jpg の実体が PNG/WebP のことがある）。
    除去できない場合は元のバイト列を返さない（fail closed）。応答は②④と同じ 404 に
    する: 5xx にすると壊れた1枚が閲覧されるたびに 5xx バースト通知
    （core/alert_middleware.py）を鳴らし続ける恒常的な誤アラート源になり、専用の
    文言にすると「実在するが配信できない」を見分けるオラクルになるため。原因の
    追跡は warning ログ（マスク済み storage_key・累計件数。閲覧のたびにログを埋め
    ないよう 60 秒に 1 行へ間引く）で行う。libjpeg が警告付きで表示できる程度の
    JPEG の破損（EOI 欠落等）は除去側で受け付けるため、ここには来ない（QA M1）。
    304 経路は本体を返さないため除去は不要。
    """
    if operator is not None and (
        operator.is_suspended or operator.vendor_status not in OPERATOR_CASE_VIEW_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                SUSPENDED_ACCOUNT_DETAIL
                if operator.is_suspended
                else OPERATOR_APPROVAL_REQUIRED_DETAIL
            ),
        )

    if not storage.is_valid_key(storage_key):
        raise _FILE_NOT_FOUND

    etag = f'"{storage_key}"'
    cache_headers = {
        "ETag": etag,
        "Cache-Control": "private, no-cache",
        "Vary": "Authorization",
        "X-Content-Type-Options": "nosniff",
    }

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and _if_none_match_matches(if_none_match, etag):
        try:
            if not await storage.exists(storage_key):
                raise _FILE_NOT_FOUND
        except StorageUnavailableError as exc:
            raise _SERVE_STORAGE_UNAVAILABLE from exc
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=cache_headers)

    try:
        obj = await storage.read_bytes(storage_key)
    except StorageUnavailableError as exc:
        raise _SERVE_STORAGE_UNAVAILABLE from exc
    if obj is None:
        raise _FILE_NOT_FOUND

    image_ext = storage.sniff_image_ext(obj.data)
    try:
        if image_ext is None:
            raise ImageMetadataError("JPEG / PNG / WebP のシグネチャではありません")
        sanitized_data = await asyncio.to_thread(strip_image_metadata, obj.data, image_ext)
    except ImageMetadataError as exc:
        _note_serve_strip_failure(storage_key, exc)
        raise _FILE_NOT_FOUND from exc

    return Response(content=sanitized_data, media_type=obj.content_type, headers=cache_headers)
