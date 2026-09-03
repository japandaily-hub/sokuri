"""ローカルE2E（run_local_e2e.py で起動した使い捨てSQLite）へ、業者目線の実機検証用データを投入する。

本番DBには到達しない（対象は http://127.0.0.1:8000 のローカルAPIのみ）。
投入内容:
  - 管理者   e2e-admin@example.com / Admin-Pass-2026   （ADMIN_EMAILS に一致し role=admin）
  - 依頼者   seller@example.com    / Seller-Pass-2026  （案件3件: 世田谷区/横浜市/さいたま市）
  - 業者A    vendor@example.com    / Vendor-Pass-2026  （招待コードで active・許可証提出済み・案件1に入札・案件2で成約）
  - 業者B    rival@example.com     / Rival-Pass-2026   （active・案件1で業者Aより高い入札 → Aは順位外）
  - 業者C    pending@example.com   / Pending-Pass-2026 （招待なし＝審査中・許可証未提出）

使い方:
    cd backend && .venv\\Scripts\\python.exe seed_local_e2e.py
"""
from __future__ import annotations

import pathlib
import sys

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
PHOTO = ROOT / "test-room.jpg"

ACCOUNTS = {
    "admin": ("e2e-admin@example.com", "Admin-Pass-2026"),
    "seller": ("seller@example.com", "Seller-Pass-2026"),
    "vendor": ("vendor@example.com", "Vendor-Pass-2026"),
    "rival": ("rival@example.com", "Rival-Pass-2026"),
    "pending": ("pending@example.com", "Pending-Pass-2026"),
}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def must(r: httpx.Response, *codes: int) -> dict:
    if r.status_code not in codes:
        print(f"!! {r.request.method} {r.request.url} -> {r.status_code}: {r.text[:300]}")
        sys.exit(1)
    return r.json() if r.content else {}


def signup_or_login_user(c: httpx.Client, email: str, password: str, name: str) -> str:
    r = c.post(f"{BASE}/auth/signup", json={"email": email, "password": password, "name": name})
    if r.status_code == 409:
        r = c.post(f"{BASE}/auth/login", json={"email": email, "password": password})
        return must(r, 200)["access_token"]
    return must(r, 201)["access_token"]


def signup_or_login_operator(c: httpx.Client, email: str, password: str, company: str, invite: str | None) -> tuple[str, str]:
    body = {
        "company_name": company,
        "email": email,
        "password": password,
        "license_number": "第301234567890号",
        "agreed": True,
    }
    if invite:
        body["invite_code"] = invite
    r = c.post(f"{BASE}/auth/operator/signup", json=body)
    if r.status_code == 409:
        r = c.post(f"{BASE}/auth/operator/login", json={"email": email, "password": password})
        d = must(r, 200)
        return d["access_token"], d["operator"]["id"]
    d = must(r, 201)
    return d["access_token"], d["operator"]["id"]


def upload_photo(c: httpx.Client, token: str) -> str:
    pre = must(c.post(f"{BASE}/upload/presign", json={"filename": "room.jpg", "content_type": "image/jpeg"}, headers=auth(token)), 200)
    r = c.put(f"http://127.0.0.1:8000{pre['upload_url']}", content=PHOTO.read_bytes(), headers={**auth(token), "Content-Type": "image/jpeg"})
    must(r, 204, 200)
    return pre["storage_key"]


def create_case(c: httpx.Client, token: str, *, purpose: str, pref: str, city: str, items: list[str]) -> dict:
    payload = {
        "purpose": purpose,
        "prefecture": pref,
        "city": city,
        "address_detail": "1-2-3 テストハイツ 201",
        "housing_type": "マンション",
        "floor_plan": "2LDK",
        "floor_number": 2,
        "has_elevator": True,
        "items": [
            {"name": name, "sort_order": i, "photos": [{"storage_key": upload_photo(c, token), "sort_order": 0}]}
            for i, name in enumerate(items)
        ],
    }
    return must(c.post(f"{BASE}/cases", json=payload, headers=auth(token)), 201)


def main() -> None:
    with httpx.Client(timeout=60) as c:
        must(c.get("http://127.0.0.1:8000/health"), 200)

        admin_tok = signup_or_login_user(c, *ACCOUNTS["admin"], "運営 太郎")
        seller_tok = signup_or_login_user(c, *ACCOUNTS["seller"], "出品 花子")

        existing = must(c.get(f"{BASE}/cases", headers=auth(seller_tok)), 200)
        if existing:
            print(f"既に案件 {len(existing)} 件があるためシード済みとみなして終了します。作り直す場合は e2e_local.db を削除して再起動してください。")
            return

        case1 = create_case(c, seller_tok, purpose="引っ越し", pref="東京都", city="世田谷区", items=["ソファ", "ダイニングテーブル", "冷蔵庫"])
        case2 = create_case(c, seller_tok, purpose="遺品整理", pref="神奈川県", city="横浜市青葉区", items=["タンス", "食器一式"])
        case3 = create_case(c, seller_tok, purpose="断捨離", pref="埼玉県", city="さいたま市浦和区", items=["本棚"])

        def invite() -> str:
            return must(c.post(f"{BASE}/admin/invites", json={}, headers=auth(admin_tok)), 201)["code"]

        vendor_tok, vendor_id = signup_or_login_operator(c, *ACCOUNTS["vendor"], "テスト買取センター株式会社", invite())
        rival_tok, _ = signup_or_login_operator(c, *ACCOUNTS["rival"], "ライバル片付けサービス", invite())
        pending_tok, _ = signup_or_login_operator(c, *ACCOUNTS["pending"], "審査中リサイクル商店", None)

        # 業者Aは許可証を提出済みにする
        must(
            c.post(f"{BASE}/operator/license-image", files={"file": ("license.jpg", PHOTO.read_bytes(), "image/jpeg")}, headers=auth(vendor_tok)),
            200,
        )

        # 案件1: A 30,000 → B 45,000（Aは順位外）
        must(c.post(f"{BASE}/cases/{case1['id']}/bids", json={"amount": 30000, "message": "まとめて引き取ります。"}, headers=auth(vendor_tok)), 201)
        must(c.post(f"{BASE}/cases/{case1['id']}/bids", json={"amount": 45000, "message": "即日対応可能です。"}, headers=auth(rival_tok)), 201)
        # 案件2: A 20,000 → 依頼者が A を選択（成約）
        bid = must(c.post(f"{BASE}/cases/{case2['id']}/bids", json={"amount": 20000, "message": "丁寧に運び出します。"}, headers=auth(vendor_tok)), 201)
        must(c.post(f"{BASE}/cases/{case2['id']}/bids/{bid['id']}/select", headers=auth(seller_tok)), 201)
        # 案件3: 入札なし（open）

        print("シード完了。ログイン情報:")
        for k, (e, p) in ACCOUNTS.items():
            print(f"  {k:8s} {e:28s} {p}")
        print(f"案件: {case1['id']} / {case2['id']} / {case3['id']}  業者A id={vendor_id}")


if __name__ == "__main__":
    main()
