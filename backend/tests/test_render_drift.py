"""render.yaml と Render 実態の突き合わせ（scripts/render_drift_check.py）。

INC-2026-09-07-1 の再発防止: DB の plan / databaseName のズレを必ず検出し、一致なら何も出ないことを固定する。
"""

from __future__ import annotations

import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from render_drift_check import compare  # noqa: E402

SPEC = {
    "databases": [{"name": "sokuri-db", "databaseName": "sokuri_jwd3", "user": "sokuri", "plan": "basic_256mb", "region": "oregon", "ipAllowList": []}],
    "services": [
        {
            "type": "web",
            "name": "sokuri-backend",
            "plan": "free",
            "region": "oregon",
            "branch": "main",
            "autoDeploy": True,
            "healthCheckPath": "/health",
            "dockerfilePath": "./backend/Dockerfile",
            "dockerContext": "./backend",
            "envVars": [
                {"key": "DATABASE_URL", "fromDatabase": {"name": "sokuri-db", "property": "connectionString"}},
                {"key": "GOOGLE_API_KEY", "sync": False},
                {"key": "JWT_SECRET", "generateValue": True},
                {"key": "PORT", "value": 8000},
                {"key": "DIAG_TOKEN", "sync": False},
            ],
        }
    ],
}
LIVE_DB = {"plan": "basic_256mb", "databaseName": "sokuri_jwd3", "region": "oregon", "ipAllowList": []}
LIVE_SERVICE = {
    "branch": "main",
    "autoDeploy": "yes",
    "serviceDetails": {
        "plan": "free",
        "region": "oregon",
        "healthCheckPath": "/health",
        "envSpecificDetails": {"dockerfilePath": "./backend/Dockerfile", "dockerContext": "./backend"},
    },
}
LIVE_ENV = {"DATABASE_URL", "GOOGLE_API_KEY", "JWT_SECRET", "PORT"}


def test_no_drift_when_everything_matches():
    drifts, infos = compare(SPEC, LIVE_DB, LIVE_SERVICE, LIVE_ENV)
    assert drifts == []
    assert any("DIAG_TOKEN" in i for i in infos)  # sync:false の未設定は情報のみ


def test_detects_the_2026_09_07_incident_db_plan_and_name_drift():
    stale = {**LIVE_DB}
    spec = {**SPEC, "databases": [{**SPEC["databases"][0], "plan": "free", "databaseName": "sokuri"}]}
    drifts, _ = compare(spec, stale, LIVE_SERVICE, LIVE_ENV)
    assert any(d.startswith("DB.plan:") for d in drifts)
    assert any(d.startswith("DB.databaseName:") for d in drifts)


def test_detects_service_field_drift_and_missing_declared_env():
    live = {**LIVE_SERVICE, "branch": "develop"}
    drifts, _ = compare(SPEC, LIVE_DB, live, LIVE_ENV - {"PORT"})
    assert any(d.startswith("service.branch:") for d in drifts)
    assert any(d.startswith("env PORT:") for d in drifts)


def test_missing_resources_are_drift():
    drifts, _ = compare(SPEC, None, None, None)
    assert len(drifts) == 2
