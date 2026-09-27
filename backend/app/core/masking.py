"""機微データの表示用マスキングユーティリティ。

元々 ``admin.py`` にプライベート関数として実装されていたが、
``users.py`` / ``user_identity.py`` 側の依頼者向け口座マスク表示でも
同一ロジックが必要になったため、共通モジュールへ切り出す（DRY原則）。
"""

from __future__ import annotations

import re

#: メールアドレスのローカル部に使える文字（Unicode の文字・数字と RFC 5322 の記号。EmailStr が
#: 受け付ける ``= / ! #`` 等を含む。含めないと ``taro=shop@x.jp`` の ``taro=`` が平文で残る）。
_EMAIL_LOCAL_CLASS = r"[\w.!#$%&'*+/=?^`{|}~-]"

#: 自由文に紛れ込んだメールアドレスを拾う正規表現（:func:`mask_emails_in_text` 用）。
#: - 既知のラベル ``email=`` ``admin_email=`` は残す（照合の手掛かり）。それ以外の ``xxx=`` は
#:   ローカル部として一緒に隠れる（隠す側に倒す）。``admin-grant:<addr>`` の ``:`` は区切りになる。
#: - ドメイン部はドットを1つ以上要求する（``@router`` のような語や ``user@localhost`` は対象外）。
#: - 全ログ行に掛かる（app/core/app_logging.py）ため計算量を線形に保つ: 先頭の後ろ読みで
#:   ローカル部の途中からの照合をやり直さず、所有量指定子（``++``・Python 3.11+）で後戻りを
#:   させない（無いと「長い英数字の連続＋@」で開始位置ごとに再走査し、2万字で数秒かかる）。
_EMAIL_IN_TEXT_RE = re.compile(
    r"(?<!" + _EMAIL_LOCAL_CLASS + r")"
    r"(?P<label>(?:admin_)?email=)?"
    r"(?P<address>" + _EMAIL_LOCAL_CLASS + r"++@[\w-]++(?:\.[\w-]++)+)"
)

#: 1段目で拾えない「記号でつながった2件目以降」（例: ``to=a@x.jp&cc=b@y.jp`` の ``b@y.jp``）を拾う
#: 2段目。1段目は後ろ読みでローカル部の途中からの照合を止めているため、直前のメールのドメインから
#: 記号で連続する部分は開始位置になれない。区切りに使われる記号の直後からだけ、記号を含まない狭い
#: ローカル部で照合する（所有量指定子で線形のまま。マスク済みの ``t***@...`` は ``*`` の直後が
#: ``@`` でローカル部が空になるので一致しない）。
_EMAIL_AFTER_SYMBOL_RE = re.compile(r"(?<=[!#$%&'*/=?^`{|}~])[\w.+-]++@[\w-]++(?:\.[\w-]++)+")

#: 写真の storage_key（app/services/storage.py の new_storage_key: 32桁 hex＋拡張子）。無認証の
#: capability URL（GET /files/{storage_key}）なので、storage.mask_key_for_log と同じく先頭8字だけ残す。
_STORAGE_KEY_IN_TEXT_RE = re.compile(
    r"(?<![0-9A-Za-z])([a-f0-9]{8})[a-f0-9]{24}\.(?:jpe?g|png|webp)(?![0-9A-Za-z])"
)

#: LINE の userId（"U"＋32桁 hex・auth.py の _LINE_USER_ID_RE）。Push の宛先そのものなので、
#: line_notify._mask_line_user_id と同じく先頭4字だけ残す。
_LINE_USER_ID_IN_TEXT_RE = re.compile(r"(?<![0-9A-Za-z])(U[0-9a-f]{3})[0-9a-f]{29}(?![0-9A-Za-z])")

#: 写真の capability URL の区間（``GET /api/v1/files/{storage_key}``・``PUT /api/v1/upload/{storage_key}``。
#: ID 以外のパス引数を持つルートはこの2つだけ＝2026-09-27 に実アプリのルート表で確認）。
#: storage_key の形式に合わない値も含め、直後の区間を先頭8字＋``...``に丸める（隠す側に倒す）。
#: 8字以下の区間（``/upload/presign`` 等）はそのまま残る。
_CAPABILITY_PATH_SEGMENT_RE = re.compile(r"(/(?:files|upload)/)([^/?]{8})[^/?]+")

#: クエリの名前として残してよい形（英字か ``_`` で始まる 32 字以内の識別子）。値は常に伏せる。
_QUERY_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}")

#: 伏せた値の表記。
_MASKED_VALUE = "***"


def mask_account_number(account_number: str) -> str:
    """口座番号の下4桁のみ残しマスクする。4桁以下はそのまま返さず全マスクする。"""
    if len(account_number) <= 4:
        return "*" * len(account_number)
    return "*" * (len(account_number) - 4) + account_number[-4:]


def mask_email(email: str) -> str:
    """メールアドレスをログ出力用にマスクする（先頭1文字 + ``***`` + ドメイン部）。

    例: ``"user@example.com"`` -> ``"u***@example.com"``。宛先メールアドレスは
    ログ集約基盤（外部 SaaS 含む）へ平文のまま流出しうる PII のため、
    エラーログ等の非構造化出力へ載せる際は本関数を経由すること
    （security review 2026-09-18 Low: BREVO_API_KEY 未設定スキップの
    ログが宛先を平文出力していた）。``@`` を含まない/空文字列等の不正な
    値は全体をマスクして返す（フォールバックで平文が漏れないようにする）。
    """
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_emails_in_text(text: str) -> str:
    """自由文に含まれるメールアドレスをすべて :func:`mask_email` の形式に置き換える。

    例: ``"email=user@example.com\\nuser_id=1"`` -> ``"email=u***@example.com\\nuser_id=1"``。
    呼び出し側で値が分かっている場合は、従来どおり :func:`mask_email` で個別にマスクすること
    （本関数は取りこぼし対策）。マスク済みの ``u***@example.com`` は何度掛けても変わらない。
    """
    if not text or "@" not in text:
        return text
    masked = _EMAIL_IN_TEXT_RE.sub(
        lambda match: (match.group("label") or "") + mask_email(match.group("address")), text
    )
    return _EMAIL_AFTER_SYMBOL_RE.sub(lambda match: mask_email(match.group(0)), masked)


def mask_sensitive_in_text(text: str) -> str:
    """自由文中のメールアドレス・写真の storage_key・LINE の userId をまとめてマスクする。

    運営アラートの本文をそのままログへ書く箇所（services/alerts.py）と、ログ出力の直前の
    安全網（app/core/app_logging.py）で使う。呼び出し側で値が分かっている場合は、従来どおり
    :func:`mask_email`・``storage.mask_key_for_log``・``line_notify._mask_line_user_id`` で
    個別にマスクすること（本関数は取りこぼし対策）。
    """
    if not text:
        return text
    masked = mask_emails_in_text(text)
    masked = _STORAGE_KEY_IN_TEXT_RE.sub(r"\1...", masked)
    return _LINE_USER_ID_IN_TEXT_RE.sub(r"\1…", masked)


def mask_query_string(query: str) -> str:
    """クエリ文字列の値をすべて伏せる（例: ``token=abc&q=taro@x.jp`` -> ``token=***&q=***``）。

    診断用の ``?token=``（DIAG_TOKEN）や検索語 ``?q=``（氏名・メールアドレスが入りうる）の値を
    ログに残さないため。名前は照合の手掛かりとして残すが、識別子の形でない組（``=`` の無いもの・
    ``%`` や記号を含む名前）は組ごと ``***`` にする。空の組（``&&``・末尾の ``&``）は捨てる。
    """
    masked_pairs: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        name, has_value, _ = pair.partition("=")
        if has_value and _QUERY_NAME_RE.fullmatch(name):
            masked_pairs.append(f"{name}={_MASKED_VALUE}")
        else:
            masked_pairs.append(_MASKED_VALUE)
    return "&".join(masked_pairs)


def mask_request_target_for_log(target: str) -> str:
    """ログ・運営アラートへ出す「パス（``?`` クエリ）」から、写真の鍵とクエリの値を伏せる。

    ``GET /api/v1/files/{storage_key}`` は無認証の capability URL（storage_key を知っていれば誰でも
    写真を取れる）なので、ログを読める人が写真を取れないよう次の順で処理する:

    1. ``/files/``・``/upload/`` の直後の区間を先頭8字＋``...``にする（``storage.mask_key_for_log`` と
       同じ形。形式に合わない値も丸める）。
    2. パスの残りに :func:`mask_sensitive_in_text` を掛ける（他の位置の storage_key・メール・LINE userId）。
    3. 最初の ``?`` より後ろ（クエリ）は :func:`mask_query_string` で値を伏せる。

    uvicorn のアクセスログのパスは ``urllib.parse.quote`` 済みで ``?`` は区切りにしか現れない。
    デコード済みのパス（ASGI の ``scope["path"]``）を渡す場合は、先に ``quote`` して改行・制御文字と
    ``?`` を ``%XX`` にしておくこと（core/alert_middleware.py）。
    """
    path, has_query, query = target.partition("?")
    path = mask_sensitive_in_text(_CAPABILITY_PATH_SEGMENT_RE.sub(r"\1\2...", path))
    if not has_query:
        return path
    return f"{path}?{mask_query_string(query)}"
