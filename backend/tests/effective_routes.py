"""include_router の prefix・dependencies を反映した「実際に受け付ける」ルートの列挙（構造テスト共通）。

fastapi 0.136 系までは include_router が APIRoute を prefix・依存込みで複製して
``app.routes`` に平坦に積んでいたため、``app.routes`` の APIRoute をそのまま見ればよかった。
fastapi 0.142 系では include_router が ``_IncludedRouter``（遅延ラッパ）を1件積むだけになり、
中の APIRoute は prefix 無しの元のまま。実効のパス・依存木は ``iter_route_contexts`` が返す
コンテキスト側にしか無いため、両方の版をこの形に揃えてから検査する（CI は最新版を入れる）。
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi import routing as fastapi_routing
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute


@dataclass(frozen=True)
class EffectiveApiRoute:
    """実効のパス・メソッド・依存木と、元の APIRoute（本文フィールド等の参照用）。"""

    path: str
    methods: frozenset[str]
    dependant: Dependant
    original: APIRoute

    @property
    def body_field(self) -> Any:
        return self.original.body_field


def iter_original_and_effective(app: FastAPI) -> Iterator[tuple[BaseRoute, Any]]:
    """アプリの全ルートを (元のルート, 実効ルート) の組で平坦に返す。

    新しい fastapi（``iter_route_contexts`` を持つ版）は include 済みルーターを再帰的に展開し、
    実効ルートは prefix・include 時の依存を反映した ``RouteContext``。古い fastapi は
    ``app.routes`` が既に平坦で、元のルート＝実効ルート。
    """
    iter_route_contexts = getattr(fastapi_routing, "iter_route_contexts", None)
    if iter_route_contexts is None:
        for route in app.routes:
            yield route, route
        return
    for route_context in iter_route_contexts(app.routes):
        yield route_context.original_route, route_context


def effective_api_routes(app: FastAPI) -> list[EffectiveApiRoute]:
    routes: list[EffectiveApiRoute] = []
    for original, effective in iter_original_and_effective(app):
        if not isinstance(original, APIRoute):
            continue
        assert effective.dependant is not None, f"依存木の無い APIRoute: {effective.path}"
        routes.append(
            EffectiveApiRoute(
                path=effective.path,
                methods=frozenset(effective.methods or ()),
                dependant=effective.dependant,
                original=original,
            )
        )
    return routes
