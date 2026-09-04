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
