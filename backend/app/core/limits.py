"""カタヅケ全体で共有する数量上限の一元定義。

案件写真・商品アルバムに関する上限値を schemas_katadzuke.py / services/summary.py
の複数箇所に分散させず、ここに集約する（値のズレ・改修漏れの防止）。
"""

from __future__ import annotations

# 1案件あたりの商品（CaseItem）数上限。家まるごとの一括出品を想定し 30 点（2026-09-04 引き上げ）。
MAX_ITEMS_PER_CASE = 30

# 商品1点あたりの写真数上限。撮影ガイド（全方位 4〜6 枚＋傷・汚れ 1〜3 枚＋ロゴ・型番 1〜2 枚）を
# そのまま実行しても収まるよう 12 枚（2026-09-04 引き上げ）。
MAX_PHOTOS_PER_ITEM = 12

# 1案件あたりの写真総数上限（items 配下 + 直下 photos の合計）。30 点 × 平均 5 枚を想定し 150 枚
# （2026-09-04 引き上げ）。AI 解析の Gemini 呼び出しは summary.py の予算（案件あたり 8 回・
# 商品あたり 2 枚・ungrouped 4 枚）で別途上限があり、写真枚数に比例して増えない。
MAX_PHOTOS_PER_CASE = 150

# 1取引あたりの減額申請の上限回数（却下後に1回だけ再申請できる。r8-M3）。
# reductions.py の 409 判定と TransactionDetailOut.reduction_request_limit の
# 単一の出所にする（web が「あと何回申請できるか」を自前のリテラルで持つと、
# 上限を変えた瞬間に画面と API が食い違う）。r10 V-M4 対応。
MAX_REDUCTION_REQUESTS_PER_TRANSACTION = 2

# 1取引あたりの日程候補提示（schedule_proposal）の上限回数。提示は取引の messages に
# 1件ずつ積まれるため、上限が無いと提示済み候補を走査する処理（確定時の照合など。
# 行ロックを保持したまま読む）と list_messages（ページングなしで全件を返す）の読む
# 行数が際限なく増える。1回最大10候補（ScheduleProposeRequest.slots の上限）の
# ため、走査はおおむね最大200候補で頭打ちになる（同時実行時の超過幅は
# transactions.propose_schedule のコメント参照。2026-09-26 日程API入力検証の
# セキュリティレビュー L-4）。
MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION = 20

# 1取引・当事者（sender_type）ごとの通常発言（kind="text"）の上限件数。取引全体
# で数えると片方が上限まで送り切って相手の発言枠を食い潰せてしまうため、当事者
# ごとに数える。list_messages はページングなしで全件を返すため、この上限と
# MAX_SCHEDULE_PROPOSALS_PER_TRANSACTION の2つがチャット一覧の応答件数の天井に
# なる（2026-09-26 日程API入力検証のセキュリティレビュー L-4）。
MAX_TEXT_MESSAGES_PER_PARTY_PER_TRANSACTION = 300

# 口コミ（レビューのコメント）の上限文字数。web の入力欄（web/src/lib/review-verdict.ts の
# REVIEW_COMMENT_MAX）と同じ値にする。schemas_katadzuke.ReviewCreateRequest の Field と
# 無害化（_sanitize_free_text）の両方がここを参照する（2026-09-25 に 1000 → 300。alembic 0042 の段B）。
REVIEW_COMMENT_MAX_LENGTH = 300

# 運営が口コミを削除（非表示）にするときの理由の上限文字数（reviews.hidden_reason の列長 200 と同じ）。
# schemas_katadzuke.ReviewHideRequest の Field と無害化の両方がここを参照する。web の削除ダイアログの
# 入力上限（200 字）と同じ値にする（2026-09-25 運営の口コミ管理）。
REVIEW_HIDE_REASON_MAX_LENGTH = 200

# 自社入札の引き上げ（PATCH /cases/{case_id}/bids/me）に必要な最小引き上げ幅（円）。
# web 側の入力刻みと一致させる。1円単位の無意味な引き上げ連打（通知の増幅・
# bid_amount_history の膨張）を防ぐ（security review 指摘対応）。
BID_RAISE_MIN_STEP = 1000

# 1入札あたりの引き上げ回数の上限。無制限だと同一入札に対する通知
# （dispatch_bid_updated）の連打と bid_amount_history の無制限な行数増加を
# 招くため、DoS・通知疲れ対策として上限を設ける（security review 指摘対応）。
MAX_BID_REVISIONS = 20

# 完了確定の依頼（POST /transactions/{id}/complete/request）の1取引あたり上限回数。
# 無制限だと業者が依頼者を通知で連打できてしまうため、減額申請の上限
# （MAX_REDUCTION_REQUESTS_PER_TRANSACTION）と同じ考え方で上限を設ける。
# transactions.py の 409 判定と TransactionDetailOut.completion_request_limit の
# 単一の出所にする。
MAX_COMPLETION_REQUESTS_PER_TRANSACTION = 3

# 完了確定の依頼の再送クールダウン（時間）。前回の依頼からこの時間が経つまでは
# 429 で拒否する（通知の連打防止）。transactions.py の 429 判定と
# TransactionDetailOut.completion_request_available_at の単一の出所にする。
COMPLETION_REQUEST_COOLDOWN_HOURS = 24
