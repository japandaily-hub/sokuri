"""カタヅケ全体で共有する数量上限の一元定義。

案件写真・商品アルバムに関する上限値を schemas_katadzuke.py / services/summary.py
の複数箇所に分散させず、ここに集約する（値のズレ・改修漏れの防止）。
"""

from __future__ import annotations

# 1案件あたりの商品（CaseItem）数上限。
MAX_ITEMS_PER_CASE = 10

# 商品1点あたりの写真数上限。
MAX_PHOTOS_PER_ITEM = 8

# 1案件あたりの写真総数上限（items 配下 + 直下 photos の合計）。既存値・変更しない。
MAX_PHOTOS_PER_CASE = 20
