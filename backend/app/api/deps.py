"""FastAPI deps -- JWT auth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timezone

import jwt as pyjwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models.operator import Operator
from app.db.models.user import User
from app.db.session import get_session

_bearer = HTTPBearer(auto_error=False)

_CRED_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials. Please log in again.",
    headers={"WWW-Authenticate": "Bearer"},
)


def _decode(credentials: HTTPAuthorizationCredentials | None) -> dict:
    if credentials is None or not credentials.credentials:
        raise _CRED_EXC
    try:
        payload = decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError as exc:
        raise _CRED_EXC from exc
    # reauth_token（LINE連携付与用の短命step-upトークン）等の用途限定トークンは
    # "purpose" クレームを持つ。通常のaccess_tokenにはこのクレームが無いため、
    # ここで弾かないと発行から5分間、通常の認証必須エンドポイント全てで
    # セッショントークン相当として通用してしまう（security review Medium指摘対応。
    # core/security.py の create_reauth_token のコメントは元々この分離を前提に
    # 書かれていたが、実際にはここでの検証が抜けていた）。
    if payload.get("purpose") is not None:
        raise _CRED_EXC
    return payload


def assert_user_not_revoked(user: User, payload: dict) -> None:
    """退会（論理削除）済み・パスワード変更後の旧トークンを 401 で失効させる。

    - 論理削除ゲート: deleted_at が設定済みのアカウントの旧トークンは即時失効させる。
    - パスワード変更失効ゲート: JWT の iat が password_changed_at より古い場合に拒否する。
      iat は PyJWT により epoch 秒の int にエンコードされるため、比較も int 切り捨てで行い
      同一秒内に発行された新トークンを誤って弾かないようにする。
      SQLite は tz-naive な datetime を返すため、tzinfo が無ければ UTC を補って比較する
      （tz なしのまま timestamp() するとローカルタイム解釈になりズレるため）。

    ``auth.py`` の ``line_exchange``（Bearer付き連携経路）でも同一ゲートを適用するため
    モジュール関数として公開する（旧名 ``_assert_user_not_revoked`` から改名・再利用）。
    """
    if user.deleted_at is not None:
        raise _CRED_EXC

    if user.password_changed_at is None:
        return
    iat = payload.get("iat")
    if iat is None:
        return
    changed_at = user.password_changed_at
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    if int(iat) < int(changed_at.timestamp()):
        raise _CRED_EXC


# 依頼者停止時の 403 detail（security review L-2対応）。従来は文言のみの文字列
# だったため、web 側が文字列一致でしかハンドリングできなかった。code を機械可読な
# 識別子として付与し、web が「停止中」表示を汎用エラーと区別できるようにする
# （FastAPI の HTTPException.detail は dict を許容する）。auth.py の signup/
# line_exchange 経路の同種チェックからも同じ定数を参照する（DRY・文言の分岐防止）。
SUSPENDED_ACCOUNT_DETAIL: dict[str, str] = {
    "code": "account_suspended",
    "message": "このアカウントは利用停止中です。お問い合わせ窓口までご連絡ください。",
}


def assert_user_not_suspended(user: User) -> None:
    """停止中（is_suspended）依頼者の旧トークンを 403 で失効させる。

    ``assert_operator_not_suspended`` の依頼者側対応（r3-verify-operator ADD-2）。
    ``get_current_user`` / ``get_current_actor`` の user 分岐、および ``auth.py`` の
    ``user_login`` / ``line_exchange``（Bearer付き連携経路・user分岐）で同一ゲートを
    適用するためにモジュール関数として公開する。公開API（/vendors 等・認証不要の
    エンドポイント）はこのゲートを経由しないため影響しない。
    """
    if user.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SUSPENDED_ACCOUNT_DETAIL,
        )


def assert_operator_not_suspended(operator: Operator) -> None:
    """停止中（is_suspended）業者の旧トークンを 403 で失効させる。

    ``get_current_operator`` / ``get_current_actor`` に元々インラインで書かれていた
    判定を抽出したもの。``auth.py`` の ``line_exchange``（Bearer付き連携経路・
    operator分岐）でも同一ゲートを適用するために再利用する。

    security review N-6 / R-L3対応: 従来は detail が文字列のままで依頼者側
    （``assert_user_not_suspended``）とは非対称だったため、web 側が
    ``detailCode==="account_suspended"`` の機械可読判定に乗れず、停止業者は
    自動サインアウトや停止案内への誘導がされなかった。依頼者側と同一の
    ``SUSPENDED_ACCOUNT_DETAIL`` を共用することで契約を一本化する。
    """
    if operator.is_suspended:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SUSPENDED_ACCOUNT_DETAIL,
        )


# ── 案件閲覧ゲート（r12 決定1・プライバシー優先）────────────────────────────
# 案件は「他人の自宅の写真・所在地・生活実態」という高機微データの集合であり、
# 運営が実在性を確認していない業者（vendor_status="pending"／"rejected"）へ
# 開示してよい情報ではない。従来は cases.py 側に「pending にも公開案件を見せる」
# 分岐（閲覧可・入札不可の非対称）を置いていたが、審査に通らない相手にまで
# 依頼者の資産情報が渡る設計そのものが不適当なため撤去し、閲覧も承認後に限定する。
#
# ``account_suspended``（停止中）とは別コードにする。停止は「一度承認された業者が
# 事後に止められた」状態で、web 側の導線（解除依頼の問い合わせ）が異なるため。
OPERATOR_APPROVAL_REQUIRED_DETAIL: dict[str, str] = {
    "code": "approval_required",
    "message": "運営の承認後に案件を閲覧できます。",
}

#: 案件の閲覧を許可する vendor_status。"limited" は入札不可のレガシー値だが、
#: 「一度は運営が実在性を確認した」区分のため閲覧は許可する（入札は
#: get_verified_operator が active のみに絞る）。
OPERATOR_CASE_VIEW_STATUSES: frozenset[str] = frozenset({"active", "limited"})


def assert_operator_case_access(operator: Operator) -> None:
    """未承認業者（pending / rejected 等）の案件閲覧を 403 で止める。

    停止中の判定を先に行い ``account_suspended`` を優先する（停止中の active 業者に
    ``approval_required`` を返すと、web が「承認待ち」という誤った案内を出すため）。
    """
    assert_operator_not_suspended(operator)
    if operator.vendor_status not in OPERATOR_CASE_VIEW_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=OPERATOR_APPROVAL_REQUIRED_DETAIL,
        )


def get_current_user_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """依頼者トークンの検証済みクレーム（sub/typ/role/iat/exp）を返す。

    ``get_current_user`` と併用し、トークンの発行時刻（iat）に依存する step-up 判定
    （例: LINE 専用ユーザーの振込口座変更は「直近ログイン」のトークンのみ許可）で使う。
    typ の検証は行うが、失効ゲート（退会・パスワード変更）は ``get_current_user`` 側が担う。
    """
    payload = _decode(credentials)
    if payload.get("typ") != "user":
        raise _CRED_EXC
    return payload


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    payload = _decode(credentials)
    if payload.get("typ") != "user":
        raise _CRED_EXC
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise _CRED_EXC
    assert_user_not_revoked(user, payload)
    assert_user_not_suspended(user)
    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user


async def get_current_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Operator:
    payload = _decode(credentials)
    if payload.get("typ") != "operator":
        raise _CRED_EXC
    operator = await session.get(Operator, uuid.UUID(payload["sub"]))
    if operator is None:
        raise _CRED_EXC
    # 論理削除ゲート（依頼者側 assert_user_not_revoked と同じ趣旨・r8-M6）:
    # 退会済み業者の旧トークンは即時失効させる。これが無いと、退会直後の
    # 発行済みトークンで最長トークン有効期限ぶん操作を続けられてしまう。
    if operator.deleted_at is not None:
        raise _CRED_EXC
    assert_operator_not_suspended(operator)
    return operator


async def get_verified_operator(
    operator: Operator = Depends(get_current_operator),
) -> Operator:
    """入札等のフル稼働操作を許可するゲート。

    全業者は admin 承認必須。vendor_status="active" の業者のみ許可する
    （"pending"=未承認、"limited"=レガシー値のいずれも入札不可）。
    案件の**閲覧**はこれより一段緩い ``assert_operator_case_access``
    （active / limited を許可）で判定する（r12 決定1: 従来 pending にも
    公開案件を見せていた分岐は撤去済み）。
    """
    if operator.vendor_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="アカウントは承認待ちです。運営の承認完了後に入札などの操作ができるようになります。",
        )
    # N-6対応: assert_operator_not_suspended と同一の dict detail を使う
    # （複製されていた文字列 detail を残すと契約が再度非対称に戻るため）。
    assert_operator_not_suspended(operator)
    return operator


@dataclass
class Actor:
    """Either user or operator principal."""

    typ: str
    user: User | None = None
    operator: Operator | None = None

    @property
    def id(self) -> uuid.UUID:
        obj = self.user if self.typ == "user" else self.operator
        assert obj is not None
        return obj.id


async def get_current_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Actor:
    payload = _decode(credentials)
    typ = payload.get("typ")
    subject_id = uuid.UUID(payload["sub"])
    if typ == "user":
        user = await session.get(User, subject_id)
        if user is None:
            raise _CRED_EXC
        assert_user_not_revoked(user, payload)
        assert_user_not_suspended(user)
        return Actor(typ="user", user=user)
    if typ == "operator":
        operator = await session.get(Operator, subject_id)
        if operator is None:
            raise _CRED_EXC
        assert_operator_not_suspended(operator)
        return Actor(typ="operator", operator=operator)
    raise _CRED_EXC


async def get_case_viewer_actor(
    actor: Actor = Depends(get_current_actor),
) -> Actor:
    """案件系エンドポイント（一覧・詳細・入札一覧）の共通閲覧ゲート（r12 決定1）。

    依頼者・運営は従来どおり素通し、業者のみ ``assert_operator_case_access`` を適用する。
    個々のハンドラで vendor_status を判定すると新規エンドポイント追加時に漏れるため、
    Depends 側に一本化する（``cases.py`` / ``bids.py`` から共用）。
    """
    if actor.typ == "operator":
        assert actor.operator is not None
        assert_operator_case_access(actor.operator)
    return actor


async def get_optional_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Operator | None:
    """Authorization ヘッダがあれば業者を解決する「任意認証」（無ければ None）。

    ``GET /files/{storage_key}``（無認証の capability URL。``<img>`` から Authorization
    ヘッダ無しで叩かれる前提のため必須認証にはできない）に案件写真の閲覧ゲートを
    後付けするための依存。トークンが無い・壊れている・依頼者トークンである場合は
    ``None`` を返して従来どおりの配信に委ねる（既存の無認証配信を 401 化しない）。
    業者トークンとして正当に解決できた場合のみ、停止・未承認のゲートを適用できる。

    セッションは ``Depends`` で受けるが、``AsyncSession`` の生成自体は DB 接続を
    借りない（最初のクエリ発行時に初めてチェックアウトされる）。したがって
    トークンを持たない大多数の画像リクエストではプール消費がゼロのままになる。
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
    except pyjwt.PyJWTError:
        return None
    if payload.get("purpose") is not None or payload.get("typ") != "operator":
        return None
    subject = payload.get("sub")
    if not subject:
        return None
    try:
        operator_id = uuid.UUID(str(subject))
    except ValueError:
        return None
    operator = await session.get(Operator, operator_id)
    if operator is None or operator.deleted_at is not None:
        return None
    return operator
