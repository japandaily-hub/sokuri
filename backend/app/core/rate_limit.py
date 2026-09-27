"""レート制限のドメイン層（フレームワーク非依存）。

設計書（認証系レート制限）§1 の方式選定に基づく自前実装。**このモジュールは
FastAPI を import しない**。単体テストを HTTP なしで書けるようにするための
制約であり、崩してはならない。

アルゴリズム: 固定ウィンドウ（fixed window）。キーあたり
``(window_start_monotonic, count, window_seconds, limit)`` の1組のみを
保持するため、キーあたりメモリは O(1)（スライディングログのように失敗回数分の
リストを持たない。攻撃者がリストを膨らませて新たな DoS 面を作れてしまうため）。
これとは別に、照合中の予約（下記）を key ごとに最大 limit 件だけ持つ。

既知の弱点として、ウィンドウ境界で瞬間的に最大2倍のバーストを許すが、
オンライン総当たり対策としては無意味な差として受容する（設計書 §1）。

失敗のみカウント方式（login 等）の照合は、記録済みの回数とは別に「照合中の予約」
（``reserve``/``release``）も上限の判定に数える。同時に届いた要求が、ほかの要求の失敗が
記録される前にそろって判定を通り、上限を超えて照合できてしまうのを防ぐため
（2026-09-27 セキュリティレビュー M-3。使い方は ``app.api.rate_limit_deps.PasswordAttempt``）。

将来のスケール移行パス: ``RateLimitStore`` を Protocol（Port）として定義し、
``InMemoryRateLimitStore`` を唯一の実装として出荷する。将来インスタンスが
2つ以上になった時点で ``RedisRateLimitStore`` を追加し、
``get_rate_limiter()`` の生成箇所1行の差し替えのみで移行できる
（ハンドラ・ガード・テストは無変更）。
"""

from __future__ import annotations

import heapq
import logging
import math
import time
from dataclasses import dataclass
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

# RL_MAX_KEYS 到達 WARNING のログスパム防止（前回出力から60秒以上経過時のみ再出力）。
_MAX_KEYS_WARN_INTERVAL_SEC = 60.0

# hit() 呼び出しがこの回数に達するたび、窓経過済みエントリの定期スイープを行う。
_SWEEP_EVERY = 256

# ハードキャップ到達時、毎回1件ずつ削るのではなく max_keys の90%まで一気に
# 退避する（ヒステリシス）。security review H-1 対応: 張り付き状態
# （len==max_keys が続き、以後の hit 毎回 O(n log n) の退避処理が走る）を防ぎ、
# 償却 O(1) にする。
_CAP_HYSTERESIS_RATIO = 0.9


@dataclass(frozen=True)
class RateLimitVerdict:
    """1回の判定結果。"""

    allowed: bool
    remaining: int
    retry_after_seconds: int


@dataclass(frozen=True)
class RateLimitReservation:
    """``reserve`` の結果。許可されたときだけ ``token`` を持つ（``release`` に渡す）。"""

    verdict: RateLimitVerdict
    token: int | None


@dataclass(frozen=True)
class RateLimitRule:
    """1つの軸（アカウント / IP 等）に対する上限値と窓の長さ。"""

    max_requests: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitConfig:
    """全スコープ分のルールと、機能全体の有効/無効フラグ（緊急無効化スイッチ）。"""

    enabled: bool
    login_account: RateLimitRule
    login_ip: RateLimitRule
    sensitive_account: RateLimitRule
    signup_ip: RateLimitRule
    line_ip: RateLimitRule
    max_keys: int
    # 案件作成（IP軸・アカウント軸とも全リクエストカウント）。AI解析(Gemini呼び出し)を
    # 伴うコストDoS対策（security review 指摘対応）。デフォルト値は既存の
    # RateLimitConfig(...) 呼び出し箇所（テスト含む）を壊さないために設定する
    # （既存フィールドはデフォルト無しのため、この2フィールドは末尾に追加する）。
    case_create_ip: RateLimitRule = RateLimitRule(10, 3600)
    case_create_account: RateLimitRule = RateLimitRule(10, 3600)
    # 無認証の公開参照（業者一覧・公開プロフィール）。IP軸・全リクエストカウント。
    public_read_ip: RateLimitRule = RateLimitRule(120, 60)
    # 無認証の業者事前申込（POST /operator-applications）。IP軸・全リクエストカウント。
    # 値は従来のエンドポイント内のコード定数（同一IPから1時間5件）を引き継ぐ。
    # 従来どおり環境変数は持たず、get_rate_limiter() でも上書きしない。
    operator_application_ip: RateLimitRule = RateLimitRule(5, 3600)
    # チャット送信・日程候補提示（いずれもアカウント軸のみ・全取引合計でカウント。
    # 認証済みの当事者のみが呼べるため IP 軸は持たない）。デフォルト値は既存の
    # RateLimitConfig(...) 呼び出し箇所（テスト含む）を壊さないために設定する
    # （2026-09-26 日程API入力検証のセキュリティレビュー L-4）。
    message_send_account: RateLimitRule = RateLimitRule(30, 60)
    schedule_propose_account: RateLimitRule = RateLimitRule(10, 600)


class RateLimitStore(Protocol):
    """レート制限の状態を保持するストアの Port（フレームワーク非依存）。

    将来 Redis 実装（``RedisRateLimitStore``）へ差し替える際も、この
    Protocol を満たす形でのみ実装すること。``hit``/``peek`` はそれぞれ
    Redis の ``INCR``+``EXPIRE`` / ``GET`` に自然に対応する形に限定している。
    """

    def hit(self, key: str, window_seconds: int, limit: int) -> RateLimitVerdict:
        """カウントを1増やした上で判定する（消費あり）。"""
        ...

    def peek(self, key: str, window_seconds: int, limit: int) -> RateLimitVerdict:
        """カウントを増やさず判定のみ行う（消費なし。照合中の予約も数える）。"""
        ...

    def reset(self, key: str) -> None:
        """該当キーの記録済みの回数を消去する（照合中の予約は消さない）。"""
        ...

    def reserve(self, key: str, window_seconds: int, limit: int) -> RateLimitReservation:
        """照合を始める直前に、枠を1つ予約する（失敗のみカウント方式の同時送信対策）。

        「窓内の記録済みの回数 + 予約中の数 + これからの1回」が ``limit`` 以下なら予約して
        token を返し、超えるなら予約せずに不許可の判定だけを返す。記録済みの回数は
        増やさない（失敗は従来どおり ``hit`` で記録する）。予約は ``release`` で外すか、
        予約から ``window_seconds`` が経つまで、以後の ``reserve``・``peek`` に数える。
        Redis では key ごとの ZSET（token → 期限）と Lua（期限切れの削除 → ZCARD と
        回数の GET → ZADD）で同じ意味になる。
        """
        ...

    def release(self, key: str, token: int) -> None:
        """``reserve`` の予約を外す（不明・期限切れの token なら何もしない）。"""
        ...

    def clear(self) -> None:
        """全状態を消去する（テスト専用。Redis 実装では ``NotImplementedError`` で構わない）。"""
        ...


class InMemoryRateLimitStore:
    """プロセス内メモリのみで完結する固定ウィンドウ実装。

    Render 無料プラン（水平スケールなし・単一インスタンス）を前提にした
    唯一の実装。プロセス内メモリが唯一の一貫した共有状態であり、
    Redis は無料プランでは実質選択肢がない（設計書 §1）。

    **並行性についての前提（重要・崩してはならない）**: uvicorn の単一
    イベントループ上で、``hit``/``peek``/``reserve``/``release`` の呼び出しが
    ``await`` を挟まない同期コードとして実行されることを要求する。ミューテーション
    区間に ``await`` を入れないことが唯一の排他条件であり、その前提が守られる
    限りロックは不要かつ入れてはならない（不要な直列化・デッドロック面を
    増やすだけのため）。

    ただしこの前提が守るのは「1回の呼び出しの中」だけで、呼び出し側が peek と
    hit の間に ``await`` を挟めば、その間に別の要求が同じ peek を通る。失敗のみ
    カウント方式の照合で「判定してから記録する」ときは、判定を ``reserve`` で行い、
    照合中の要求を予約として数える（``reserve`` 参照）。

    メモリ管理は三段構え（設計書 §7、ただし security review 指摘 H-1/M-4/L-5
    対応でキャップ処理の実装は設計書時点から強化している）:
      1. **遅延削除**: 窓が経過済みのキーは ``hit``/``peek`` 時に新しい窓で
         上書きする（メモリ増加なし）。
      2. **定期スイープ**: ``hit`` 呼び出し回数が ``_SWEEP_EVERY`` に達する
         たび、窓経過済みの全エントリを走査して削除する。バックグラウンド
         タスクは使わない（ライフサイクル管理とテスト容易性の負債になる
         ため）。バケットは自身の ``window_seconds`` を保持しているため
         （後述）、スイープの経過判定はキー毎に正確に行える。
      3. **ハードキャップ**（``max_keys``）: 超過時はまずスイープを実行し、
         それでも超過するなら退避する。退避は次の2点を security review
         指摘（H-1: CPU DoS、M-4/L-5: 退避ポリシーが攻撃者に有利）を受けて
         強化している:
           - **退避優先度**: 「上限に到達していない（＝無害な）キーを
             count 昇順で優先的に退避し、上限到達済み（＝ブロック中で
             被害者を守っている）キーは最終手段としてのみ退避する」。
             固定ウィンドウでは被害者バケットの ``window_start`` は
             最初の失敗時刻のまま動かないため、単純な「最古優先」だと
             時間が経つほど被害者バケットから追い出される逆転現象が
             起きる。優先度に count（および limit との比較）を使うことで
             これを防ぐ。``sorted()`` ではなく ``heapq.nsmallest`` を使い
             計算量を抑える。
           - **ヒステリシス**: 超過の都度1件ずつ削るのではなく、
             ``max_keys * 0.9`` まで一気に退避する。これにより
             「``len(buckets) == max_keys`` に張り付いて以後の ``hit`` 毎回
             重い退避処理が走る」状態（CPU DoS）を防ぎ、退避処理の呼び出し
             頻度を償却 O(1) にする。
         **これは意図的なフェイルオープン**: メモリ枯渇によるプロセス
         クラッシュ（＝全断）は、レート制限が一時的に緩むことより明確に
         悪いという判断による。キャップ到達は異常事態のため WARNING ログを
         出す（スパム防止のため60秒に1回まで）。
    """

    def __init__(
        self,
        max_keys: int = 10000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # _Bucket = (window_start: float, count: int, window_seconds: int, limit: int)。
        # window_seconds/limit をバケットに持たせることで、スイープの経過判定を
        # キー毎に正確に行え、かつキャップ退避時に「上限到達済みか」を判定できる
        # （security review 対応。以前は _max_window_seen という全scope共通の
        # 概算閾値を使っており、900秒窓のキーが最大3600秒残ってしまっていた）。
        self._buckets: dict[str, tuple[float, int, int, int]] = {}
        # 照合中の予約（``reserve``）: key → {token: 期限（clock の値）}。記録済みの回数
        # （_buckets）とは別に持つ。予約は同時に照合している要求の数だけしか無く、要求の
        # 終わりに ``release`` で消える。外し忘れ（実装の不具合）があっても期限（予約時の
        # その key の窓の長さ）で消えるので、枠が恒久的に減ることはない。max_keys の
        # 対象外（件数は同時に処理中の要求の数で上から抑えられるため）。
        self._reservations: dict[str, dict[int, float]] = {}
        self._last_reservation_token = 0
        self._max_keys = max_keys
        self._clock = clock
        self._hit_count = 0
        self._last_max_keys_warn = float("-inf")

    def __len__(self) -> int:
        return len(self._buckets)

    def _make_verdict(
        self, window_start: float, count: int, window_seconds: int, limit: int
    ) -> RateLimitVerdict:
        now = self._clock()
        elapsed = now - window_start
        remaining_window = max(window_seconds - elapsed, 0.0)
        allowed = count <= limit
        if allowed:
            retry_after = 0
        else:
            # 遅延削除の仕組み上、窓が経過済みならこの分岐に来る前に
            # 新しい窓へリセット済みのため、ここでは elapsed < window_seconds
            # が常に成立し remaining_window > 0（切り上げで必ず1以上になる）。
            retry_after = max(int(math.ceil(remaining_window)), 1)
        return RateLimitVerdict(
            allowed=allowed,
            remaining=max(limit - count, 0),
            retry_after_seconds=retry_after,
        )

    def hit(self, key: str, window_seconds: int, limit: int) -> RateLimitVerdict:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket[0] >= window_seconds:
            window_start, count = now, 0
        else:
            window_start, count = bucket[0], bucket[1]
        count += 1
        self._buckets[key] = (window_start, count, window_seconds, limit)

        self._hit_count += 1
        if self._hit_count % _SWEEP_EVERY == 0:
            self._sweep()
        self._enforce_cap()

        return self._make_verdict(window_start, count, window_seconds, limit)

    def peek(self, key: str, window_seconds: int, limit: int) -> RateLimitVerdict:
        """カウントせず判定のみ行う。

        「まだ起きていないこれからの1回」を仮に数えたとして判定する
        （``hit`` が返す post-increment の判定と揃えるため、既存カウントに
        +1 したものを ``_make_verdict`` に渡す）。これにより「失敗を
        limit 回記録済み＝次の1回は事前チェックの時点でブロックする」という
        失敗のみカウント方式（login 等）の事前チェックが正しく機能する
        （既存カウント自体と比較する ``count <= limit`` では、ちょうど
        limit 回記録済みの状態を誤って「まだ許可」と判定してしまうため）。
        照合中の予約（``reserve``）も ``reserve`` と同じく数える。
        状態は一切書き換えない（消費なし。期限切れの予約も数えないだけで消さない）。
        """
        now = self._clock()
        window_start, count = self._window_count(key, now, window_seconds)
        reserved = self._reserved_count(key, now)
        return self._make_verdict(window_start, count + reserved + 1, window_seconds, limit)

    def reserve(self, key: str, window_seconds: int, limit: int) -> RateLimitReservation:
        """照合を始める直前に枠を1つ予約する（``RateLimitStore.reserve`` 参照）。

        判定は ``peek`` と同じ「記録済みの回数 + 予約中の数 + これからの1回」。不許可の
        ときの Retry-After は、記録済みの窓の残り時間（窓がまだ無いなら窓の長さ）で、
        照合中の要求がすべて失敗した場合の値になる（成否は事前に分からないので長い方を返す）。
        """
        now = self._clock()
        self._drop_expired_reservations(key, now)
        window_start, count = self._window_count(key, now, window_seconds)
        reserved = self._reserved_count(key, now)
        verdict = self._make_verdict(window_start, count + reserved + 1, window_seconds, limit)
        if not verdict.allowed:
            return RateLimitReservation(verdict=verdict, token=None)
        self._last_reservation_token += 1
        token = self._last_reservation_token
        self._reservations.setdefault(key, {})[token] = now + window_seconds
        return RateLimitReservation(verdict=verdict, token=token)

    def release(self, key: str, token: int) -> None:
        held = self._reservations.get(key)
        if held is None:
            return
        held.pop(token, None)
        if not held:
            del self._reservations[key]

    def reset(self, key: str) -> None:
        # 照合中の予約は消さない（成功した要求が、同時に照合中の別の要求の予約まで
        # 外すと、その要求の失敗が数えられる前に次の要求が判定を通れてしまうため）。
        self._buckets.pop(key, None)

    def clear(self) -> None:
        self._buckets.clear()
        self._reservations.clear()
        self._hit_count = 0

    def _window_count(self, key: str, now: float, window_seconds: int) -> tuple[float, int]:
        """key の現在の窓の開始時刻と記録済みの回数（窓が無い・経過済みなら (now, 0)）。"""
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket[0] >= window_seconds:
            return now, 0
        return bucket[0], bucket[1]

    def _reserved_count(self, key: str, now: float) -> int:
        """key の予約のうち、期限内のものの数（書き換えない）。"""
        held = self._reservations.get(key)
        if not held:
            return 0
        return sum(1 for expires_at in held.values() if expires_at > now)

    def _drop_expired_reservations(self, key: str, now: float) -> None:
        """key の期限切れの予約を消す（予約の件数は key ごとに上限以下なので O(limit)）。"""
        held = self._reservations.get(key)
        if held is None:
            return
        for token in [token for token, expires_at in held.items() if expires_at <= now]:
            del held[token]
        if not held:
            del self._reservations[key]

    def _sweep(self) -> None:
        """窓経過済みの全エントリを削除する（定期スイープ）。

        各バケットが自身の ``window_seconds`` を保持しているため、
        キー毎に正確な経過判定ができる。外し忘れた（期限切れの）予約もここで消す
        （同じ key に二度と要求が来なくても残らないように）。
        """
        now = self._clock()
        expired_keys = [
            key
            for key, (window_start, _count, window_seconds, _limit) in self._buckets.items()
            if now - window_start >= window_seconds
        ]
        for key in expired_keys:
            del self._buckets[key]
        for key in list(self._reservations):
            self._drop_expired_reservations(key, now)

    def _enforce_cap(self) -> None:
        if len(self._buckets) <= self._max_keys:
            return

        # まずスイープ（退避よりコストが低く、実害を伴わない）。
        self._sweep()
        if len(self._buckets) <= self._max_keys:
            return

        now = self._clock()
        if now - self._last_max_keys_warn >= _MAX_KEYS_WARN_INTERVAL_SEC:
            self._last_max_keys_warn = now
            logger.warning(
                "rate_limit: RL_MAX_KEYS(%d) に到達したため、上限未到達の無害なキーから"
                "優先的に退避します（意図的なフェイルオープン。メモリ枯渇による"
                "プロセスクラッシュを避けるための判断。上限到達済み＝ブロック中の"
                "キーは最終手段としてのみ退避対象にする）。",
                self._max_keys,
            )

        # ヒステリシス: max_keys 到達の都度1件ずつではなく、90%まで一気に
        # 退避する（償却 O(1) 化。security review H-1 対応）。
        target = max(int(self._max_keys * _CAP_HYSTERESIS_RATIO), 0)
        need = len(self._buckets) - target
        if need <= 0:
            return

        def _eviction_priority(
            item: tuple[str, tuple[float, int, int, int]],
        ) -> tuple[int, float]:
            _key, (_window_start, count, _window_seconds, limit) = item
            if count < limit:
                # 群0: 上限未到達（無害）→ count 昇順で優先退避。
                return (0, count)
            # 群1: 上限到達済み（ブロック中の被害者防御）→ 最終手段のみ。
            # ここを raw count の昇順で比較すると、スコープ間で limit が
            # 異なる場合に不公平な逆転が起きる（security review Medium-1）。
            # 例: アカウント軸(limit=5)が count=6（超過比率1.2）、
            #     login IP軸(limit=20)が count=21（超過比率1.05）の場合、
            #     raw count 比較だと総当たり防御として最も価値の高い
            #     アカウント軸ブロック(count=6)の方が login IP軸ブロック
            #     (count=21)より先に退避されてしまう。limit で正規化した
            #     超過比率（count/limit）の昇順にすることで、どのスコープ
            #     由来でも「相対的に浅い超過」から退避され、「深く超過して
            #     いる（＝攻撃が継続している）」バケットほど残る。
            ratio = count / limit if limit > 0 else float("inf")
            return (1, ratio)

        victims = heapq.nsmallest(need, self._buckets.items(), key=_eviction_priority)
        for key, _bucket in victims:
            del self._buckets[key]


class RateLimiter:
    """設定・ストア・時計を束ねた高水準 API（scope/axis を跨いだ汎用実装）。

    ``enabled=False``（緊急無効化スイッチ ON）の場合、ストアには一切触れず
    常に ``allowed=True`` を返す。キルスイッチ経路にバグを混入させないため、
    ここで IP 解決やハッシュ計算より手前の最も早い段階で完全にバイパスする。

    ``store`` を明示的に渡さない場合のみ ``clock`` を使って
    ``InMemoryRateLimitStore`` を内部生成する（store を渡す場合、時計は
    その store 自身が保持するため ``clock`` は使用しない）。単体テストで
    偽クロックを注入する際は ``InMemoryRateLimitStore(clock=fake_clock)``
    を直接構築し、この ``store`` 引数で渡すこと。
    """

    def __init__(
        self,
        config: RateLimitConfig,
        store: RateLimitStore | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        # NOTE: 意図的に `store or InMemoryRateLimitStore(...)` にしない。
        # InMemoryRateLimitStore は __len__ を実装しているため、キーが0件
        # （構築直後・全キー期限切れ後）の間 bool(store) が False と評価され、
        # 明示的に渡した（空の）store が黙って新しいストアに差し替わってしまう
        # （テスト注入した FakeClock 付きストアが real time.monotonic のストアに
        # すり替わる、という発見しづらい実害のあるバグになる）。
        self._store = store if store is not None else InMemoryRateLimitStore(
            max_keys=config.max_keys, clock=clock
        )

    @property
    def config(self) -> RateLimitConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def check(self, key: str, rule: RateLimitRule) -> RateLimitVerdict:
        """カウントせず判定のみ行う（peek）。"""
        if not self._config.enabled:
            return RateLimitVerdict(
                allowed=True, remaining=rule.max_requests, retry_after_seconds=0
            )
        return self._store.peek(key, rule.window_seconds, rule.max_requests)

    def record(self, key: str, rule: RateLimitRule) -> RateLimitVerdict:
        """カウントする（hit）。"""
        if not self._config.enabled:
            return RateLimitVerdict(
                allowed=True, remaining=rule.max_requests, retry_after_seconds=0
            )
        return self._store.hit(key, rule.window_seconds, rule.max_requests)

    def reserve(self, key: str, rule: RateLimitRule) -> RateLimitReservation:
        """照合の直前に枠を予約する（reserve）。無効化中は許可のみ返し token は持たない。"""
        if not self._config.enabled:
            return RateLimitReservation(
                verdict=RateLimitVerdict(
                    allowed=True, remaining=rule.max_requests, retry_after_seconds=0
                ),
                token=None,
            )
        return self._store.reserve(key, rule.window_seconds, rule.max_requests)

    def release(self, key: str, token: int | None) -> None:
        """``reserve`` の予約を外す（token が None なら何もしない）。"""
        if token is None or not self._config.enabled:
            return
        self._store.release(key, token)

    def reset(self, key: str) -> None:
        if not self._config.enabled:
            return
        self._store.reset(key)
