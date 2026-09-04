"""app.services.vision の Gemini 呼び出し輻輳対策（Semaphore + リトライ）の単体テスト。

複数ユーザー同時アクセス時のバースト平準化（プロセス全体Semaphore）と、
429/5xx の一時障害からの自動回復（指数バックオフ+ジッタのリトライ）を検証する。
test_summary.py と同様、Gemini クライアントは monkeypatch で差し替える
（本物のAPIキー・ネットワーク通信は使わない）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai.errors import APIError

from app.services import vision as vision_module

# monkeypatch でグローバルな asyncio.sleep を差し替える前に、実物への参照を
# 保持しておく（Semaphore の同時実行数を実測するテストでは、リトライ用の
# バックオフではなく「モックGemini呼び出しの模擬レイテンシ」として本物の
# 待機が必要なため）。
_REAL_ASYNCIO_SLEEP = asyncio.sleep

# 有効なbase64 data URI（1x1透明PNGのダミーデータで足りる。内容はGemini呼び出し前の
# パース処理を通過できればよく、実画像である必要はない）。
_DUMMY_BASE_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _make_response(*, base_market_price_jpy: int = 1000) -> MagicMock:
    """generate_content が返す成功レスポンスのモック（.text にJSON文字列）。"""
    response = MagicMock()
    response.text = (
        '{"detected_name": "テスト品目", "detected_category_label": null, '
        '"category_tier": "low_value_daily", "initial_condition": "good", '
        '"condition_confidence": 0.8, "attributes": {}, '
        f'"base_market_price_jpy": {base_market_price_jpy}}}'
    )
    return response


def _api_error(code: int) -> APIError:
    """指定コードの google.genai.errors.APIError を生成する。"""
    return APIError(code, {"message": f"error code {code}"})


@pytest.fixture(autouse=True)
def _reset_gemini_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    """モジュールレベルSemaphoreをテストごとにリセットする。

    pytest-asyncio はデフォルトでテスト関数ごとに新しいイベントループを使うため、
    前のテストで生成済みのSemaphoreを使い回すと別ループ束縛のエラーになる
    （本番は単一プロセス・単一ループなのでこの問題は起きない。テスト分離のための措置）。
    """
    monkeypatch.setattr(vision_module, "_gemini_semaphore", None)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """asyncio.sleep をモック化し、リトライの待機で実テストを待たせない。"""
    sleep_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(vision_module.asyncio, "sleep", sleep_mock)
    return sleep_mock


def _patch_genai_client(
    monkeypatch: pytest.MonkeyPatch, generate_content: Callable[..., Any]
) -> None:
    """analyze_image 内の genai.Client(...) をモッククライアントに差し替える。

    ``generate_content`` は AsyncMock でも任意の async 関数でもよい
    （Semaphore の実測テストでは呼び出し中の同時実行数を計測するカスタム関数を渡す）。
    """
    fake_client = MagicMock()
    fake_client.aio.models.generate_content = generate_content
    monkeypatch.setattr(
        vision_module.genai, "Client", MagicMock(return_value=fake_client)
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """vision_module.get_settings() の戻り値を一部フィールドだけ上書きして差し替える。"""
    base_settings = vision_module.get_settings()
    patched_settings = base_settings.model_copy(update=overrides)
    monkeypatch.setattr(vision_module, "get_settings", lambda: patched_settings)


async def test_retries_after_one_429_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    """429が1回発生した後に成功した場合、リトライして最終的に成功する。"""
    generate_content = AsyncMock(side_effect=[_api_error(429), _make_response()])
    _patch_genai_client(monkeypatch, generate_content)

    result = await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    assert result.detected_name == "テスト品目"
    assert generate_content.await_count == 2


@pytest.mark.parametrize(
    "base_image",
    [
        "https://example.com/item.jpg",
        "https://169.254.169.254/latest/meta-data/",
        "http://example.com/item.jpg",
    ],
)
async def test_analyze_image_rejects_url_input_ssrf_n7(
    monkeypatch: pytest.MonkeyPatch, base_image: str
):
    """security review N-7対応: https(s):// URL は Gemini への file_data として
    素通しされず、ValueError で即座に拒否される（SSRFシンクの排除）。
    Gemini クライアントは呼ばれない（バリデーションが通信より先に走ること）。
    """
    generate_content = AsyncMock()
    _patch_genai_client(monkeypatch, generate_content)

    with pytest.raises(ValueError):
        await vision_module.analyze_image(base_image)
    generate_content.assert_not_called()


async def test_retries_after_one_503_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    """5xx（サーバ側一時障害）も同様にリトライ対象であることを確認する。"""
    generate_content = AsyncMock(side_effect=[_api_error(503), _make_response()])
    _patch_genai_client(monkeypatch, generate_content)

    result = await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    assert result.detected_name == "テスト品目"
    assert generate_content.await_count == 2


async def test_retry_exhausted_reraises_last_exception(monkeypatch: pytest.MonkeyPatch):
    """リトライ上限（既定2回=合計3試行）に達した場合、最後の例外がそのまま伝播する。"""
    persistent_error = _api_error(429)
    generate_content = AsyncMock(side_effect=persistent_error)
    _patch_genai_client(monkeypatch, generate_content)

    with pytest.raises(APIError) as excinfo:
        await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    assert excinfo.value is persistent_error
    # 既定 gemini_max_retries=2 → 初回 + リトライ2回 = 合計3試行
    assert generate_content.await_count == 3


async def test_non_retryable_400_reraises_immediately_without_retry(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: AsyncMock
):
    """400等の恒久的クライアントエラーは即座に再送出され、リトライは発生しない。"""
    client_error = _api_error(400)
    generate_content = AsyncMock(side_effect=client_error)
    _patch_genai_client(monkeypatch, generate_content)

    with pytest.raises(APIError) as excinfo:
        await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    assert excinfo.value is client_error
    assert generate_content.await_count == 1
    _no_real_sleep.assert_not_awaited()


async def test_retry_exhaustion_maps_to_503_via_analyze_endpoint(
    monkeypatch: pytest.MonkeyPatch, db_session
):
    """/analyze の503マッピング（analyze.py）が、リトライ上限到達後も従来通り機能する。

    test_api.py と同じ dependency override パターン（in-memory SQLite の
    db_session を注入）で /analyze エンドポイントを実際に叩く。
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.v1.router import api_router
    from app.db.session import get_session

    persistent_error = _api_error(500)
    generate_content = AsyncMock(side_effect=persistent_error)
    _patch_genai_client(monkeypatch, generate_content)

    app = FastAPI()

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.include_router(api_router, prefix="/api/v1")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # /analyze は認証必須（R3-operator ADD-1対応）のため、テスト用ユーザーで認証する。
        signup_res = await client.post(
            "/api/v1/auth/signup",
            json={
                "email": "vision-retry-analyze@example.com",
                "password": "password123",
                "name": "テスト太郎",
            },
        )
        assert signup_res.status_code == 201, signup_res.text
        token = signup_res.json()["access_token"]

        response = await client.post(
            "/api/v1/analyze",
            json={"base_image": _DUMMY_BASE_IMAGE},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503
    # security review M-4対応: Gemini の生例外メッセージではなく固定文言を返す
    # （内部エンドポイント情報等の漏洩防止。詳細はサーバーログにのみ残す）。
    assert response.json()["detail"] == (
        "AI サービスが一時的に利用できません。時間をおいて再度お試しください。"
    )


async def test_gemini_max_retries_zero_boundary_immediate_raise(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: AsyncMock
):
    """GEMINI_MAX_RETRIES=0 の境界値: リトライ0回設定時は初回失敗で即raiseし、
    バックオフのsleepは一度も呼ばれないことを確認する（QAレビュー指摘1）。
    """
    _patch_settings(monkeypatch, gemini_max_retries=0)
    persistent_error = _api_error(429)
    generate_content = AsyncMock(side_effect=persistent_error)
    _patch_genai_client(monkeypatch, generate_content)

    with pytest.raises(APIError) as excinfo:
        await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    assert excinfo.value is persistent_error
    assert generate_content.await_count == 1
    _no_real_sleep.assert_not_awaited()


async def test_semaphore_caps_actual_concurrent_gemini_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    """Semaphore が「プロセス全体で」実際の同時実行数を上限までしか許可しないことを
    実測する（QAレビュー指摘2）。5並列でリクエストしても、同時実行のピークが
    gemini_max_concurrent_calls=2 を超えないことを確認する。

    generate_content 呼び出し中に本物の asyncio.sleep（_REAL_ASYNCIO_SLEEP）で
    模擬レイテンシを発生させ、他タスクがそのウィンドウ内で割り込めるかを見る。
    Semaphore が機能していなければ、5タスクが実際に同時実行され peak が5に
    近づくため、上限漏れを検知できる。
    """
    _patch_settings(monkeypatch, gemini_max_concurrent_calls=2)

    state = {"active": 0, "peak": 0}

    async def fake_generate_content(*, model: str, contents: Any, config: Any) -> MagicMock:
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        # 模擬レイテンシ。Semaphore経由でpermitを保持している間だけ他タスクを
        # ブロックするはずなので、ここで実際に事件ループへ制御を返す。
        await _REAL_ASYNCIO_SLEEP(0.05)
        state["active"] -= 1
        return _make_response()

    _patch_genai_client(monkeypatch, fake_generate_content)

    await asyncio.gather(
        *(vision_module.analyze_image(_DUMMY_BASE_IMAGE) for _ in range(5))
    )

    assert state["peak"] <= 2
    # Semaphoreが全く機能していない場合（無制限）ではないことも合わせて確認する
    # （上限2に対し実際に2まで使い切っていることの確認。過度に厳格な==2ではなく
    # 上限到達の下限として>=2を課す）。
    assert state["peak"] >= 2


async def test_value_error_from_empty_response_reraises_immediately_without_retry(
    monkeypatch: pytest.MonkeyPatch, _no_real_sleep: AsyncMock
):
    """generate_content が成功応答を返しても本文が空なら ValueError になるが、
    これは APIError ではないためリトライされず即座に伝播することを確認する
    （QAレビュー指摘3）。
    """
    empty_response = MagicMock()
    empty_response.text = ""
    generate_content = AsyncMock(return_value=empty_response)
    _patch_genai_client(monkeypatch, generate_content)

    with pytest.raises(ValueError, match="Gemini からの Structured Output が空でした"):
        await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    assert generate_content.await_count == 1
    _no_real_sleep.assert_not_awaited()


async def test_backoff_sleep_does_not_hold_semaphore_permit_medium1_regression(
    monkeypatch: pytest.MonkeyPatch,
):
    """Medium-1 回帰防止テスト: バックオフの ``asyncio.sleep`` 中は Semaphore の
    permit を保持していない（＝リトライ試行ごとに acquire/release し、待機は
    Semaphore の外側で行う）ことを確認する。

    修正前は ``async with semaphore:`` の内側でリトライループ全体（sleep含む）を
    保持しており、429ストーム時に少ない permit 数（既定4）を1リクエストが
    (通信時間+バックオフ) の間占有し続け、後続リクエストが Gemini を1回も
    呼べないまま head-of-line blocking を起こしていた。
    """
    _patch_settings(
        monkeypatch, gemini_max_concurrent_calls=1, gemini_max_retries=1
    )
    generate_content = AsyncMock(side_effect=[_api_error(429), _make_response()])
    _patch_genai_client(monkeypatch, generate_content)

    # analyze_image 内部と同じ singleton を先に確定させておく（capacity=1）。
    semaphore = vision_module._get_gemini_semaphore()
    observed_value_during_sleep: dict[str, int] = {}

    async def spy_sleep(wait_sec: float) -> None:
        # バックオフ待機の瞬間、Semaphore の空き permit 数を記録する。
        observed_value_during_sleep["value"] = semaphore._value  # noqa: SLF001

    monkeypatch.setattr(vision_module.asyncio, "sleep", spy_sleep)

    await vision_module.analyze_image(_DUMMY_BASE_IMAGE)

    # capacity=1 のSemaphoreにおいて、sleep中にpermitが解放済み（=1個空き）で
    # あることを確認する。修正前の実装ではsleep中もpermit保有のため0のままになる。
    assert observed_value_during_sleep["value"] == 1
