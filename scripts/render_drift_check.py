#!/usr/bin/env python3
"""render.yaml の宣言と Render の実態（DB・サービス・環境変数キー）のズレを検出する。

2026-09-07 の障害の再発防止（docs/ops/incidents.md INC-2026-09-07-1）:
本番 DB を dashboard で有料化・作り直したのに render.yaml が `plan: free` / `databaseName: sokuri` の
ままで、Blueprint 同期が 9/1〜9/6 の間ずっと error になっていた。Render は「宣言を実態に合わせろ」と
しか言わないので、こちらで定期的に両者を突き合わせ、ズレたらその場で運営に知らせる。

比較する項目（render.yaml → Render API）:
  databases[0]  plan / databaseName / region / ipAllowList の件数
  services[0]   plan / region / branch / autoDeploy / healthCheckPath / dockerfilePath / dockerContext
  envVars       `value:` で宣言したキーが本番に存在するか（sync: false・generateValue・fromDatabase は
                dashboard 管理のため「存在しなければ情報のみ」）。値は比較しない（秘密を扱わない）。

出力: ズレがあれば ❌ で列挙し exit 1（ワークフロー側で [FAILED]/[RECOVERED] を対にして通知する）。
      なければ ✅ で exit 0。値そのものは出力しない。

環境変数:
  RENDER_API_KEY          必須（無ければスキップ・exit 0）
  RENDER_BLUEPRINT_ID     既定 exs-d8enisc2m8qs73947330（sokuri）
  RENDER_YAML             既定 render.yaml
判定の本体は compare() に分離してテストする（backend/tests/test_render_drift.py）。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "")
BLUEPRINT_ID = os.environ.get("RENDER_BLUEPRINT_ID", "exs-d8enisc2m8qs73947330")
RENDER_YAML = os.environ.get("RENDER_YAML", "render.yaml")

#: サービス側で比較する項目: (render.yaml のキー, Render API の取り出し方, 正規化)
_SERVICE_FIELDS = (
    ("plan", lambda s: s.get("serviceDetails", {}).get("plan"), str),
    ("region", lambda s: s.get("serviceDetails", {}).get("region"), str),
    ("branch", lambda s: s.get("branch"), str),
    ("autoDeploy", lambda s: s.get("autoDeploy"), lambda v: "yes" if v in (True, "yes", "true") else "no"),
    ("healthCheckPath", lambda s: s.get("serviceDetails", {}).get("healthCheckPath"), str),
    ("dockerfilePath", lambda s: s.get("serviceDetails", {}).get("envSpecificDetails", {}).get("dockerfilePath"), str),
    ("dockerContext", lambda s: s.get("serviceDetails", {}).get("envSpecificDetails", {}).get("dockerContext"), str),
)
_DB_FIELDS = (
    ("plan", lambda d: d.get("plan"), str),
    ("databaseName", lambda d: d.get("databaseName"), str),
    ("region", lambda d: d.get("region"), str),
)


def _api(path: str):
    req = urllib.request.Request(
        f"https://api.render.com/v1{path}",
        headers={"Authorization": f"Bearer {RENDER_API_KEY}", "Accept": "application/json", "User-Agent": "kdz-ops"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read())


def load_spec(path: str) -> dict:
    import yaml  # 実行環境で pip install pyyaml（ワークフロー側で準備）

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def compare(spec: dict, live_db: dict | None, live_service: dict | None, live_env_keys: set[str] | None) -> tuple[list[str], list[str]]:
    """(drifts, infos) を返す。drifts が非空なら要対応。"""
    drifts: list[str] = []
    infos: list[str] = []
    dbs = spec.get("databases") or []
    if dbs:
        want = dbs[0]
        if live_db is None:
            drifts.append(f"DB {want.get('name')}: Render 上に見つかりません（Blueprint の resources に無い）")
        else:
            for key, getter, norm in _DB_FIELDS:
                if key in want and norm(getter(live_db)) != norm(want[key]):
                    drifts.append(f"DB.{key}: render.yaml={want[key]!r} / Render={getter(live_db)!r}")
            if "ipAllowList" in want:
                want_n, live_n = len(want.get("ipAllowList") or []), len(live_db.get("ipAllowList") or [])
                if want_n != live_n:
                    drifts.append(f"DB.ipAllowList: render.yaml={want_n}件 / Render={live_n}件")
    svcs = spec.get("services") or []
    if svcs:
        want = svcs[0]
        if live_service is None:
            drifts.append(f"service {want.get('name')}: Render 上に見つかりません")
        else:
            for key, getter, norm in _SERVICE_FIELDS:
                if key in want and norm(getter(live_service)) != norm(want[key]):
                    drifts.append(f"service.{key}: render.yaml={want[key]!r} / Render={getter(live_service)!r}")
            if live_env_keys is not None:
                for ev in want.get("envVars") or []:
                    key = ev.get("key")
                    if not key or key in live_env_keys:
                        continue
                    managed = ev.get("sync") is False or ev.get("generateValue") or ev.get("fromDatabase")
                    if managed:
                        infos.append(f"env {key}: dashboard 管理のキーが本番に未設定（sync:false 等・必要なら dashboard で設定）")
                    else:
                        drifts.append(f"env {key}: render.yaml で value を宣言しているが本番に存在しない（Blueprint の envVars は既存サービスへ同期されない＝start.sh か dashboard で設定）")
    return drifts, infos


def main() -> int:
    if not RENDER_API_KEY:
        print("⏭️ RENDER_API_KEY が未設定のためスキップ")
        return 0
    spec = load_spec(RENDER_YAML)
    try:
        bp = _api(f"/blueprints/{BLUEPRINT_ID}")
        resources = {r.get("type"): r.get("id") for r in bp.get("resources") or []}
        live_db = _api(f"/postgres/{resources['postgres']}") if resources.get("postgres") else None
        live_service = _api(f"/services/{resources['web_service']}") if resources.get("web_service") else None
        env_keys: set[str] | None = None
        if resources.get("web_service"):
            env_keys = {e.get("envVar", e).get("key") for e in _api(f"/services/{resources['web_service']}/env-vars?limit=100")}
    except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:
        # API 障害で「ズレ」と誤判定しない。GitHub 側で失敗になるので気づける。
        print(f"Render API を参照できません: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    drifts, infos = compare(spec, live_db, live_service, env_keys)
    for i in infos:
        print(f"ℹ️ {i}")
    if drifts:
        print("❌ render.yaml と Render の実態がズレています（同期が error になる／設定が効いていない）:")
        for d in drifts:
            print(f"  - {d}")
        print("  → dashboard で変えた値は render.yaml に追従させる（docs/ops/incidents.md INC-2026-09-07-1）")
        return 1
    print(f"✅ render.yaml と Render の実態は一致（Blueprint status={bp.get('status')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
