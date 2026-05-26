"""SQLAlchemy の宣言的基盤（Declarative Base・共通ミックスイン・共通カラム型）。

全 ORM モデルはここで定義する ``Base`` を継承する。Alembic の autogenerate が
安定した制約名を生成できるよう、MetaData に命名規約を付与している。
"""

from __future__ import annotations

import datetime
import enum
from typing import TypeVar

from sqlalchemy import DateTime, Enum as SAEnum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Alembic autogenerate の差分を安定させるための制約命名規約。
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_EnumT = TypeVar("_EnumT", bound=enum.Enum)


class Base(DeclarativeBase):
    """全 ORM モデルの宣言的ベースクラス。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """``created_at`` / ``updated_at`` を全テーブルに付与する共通ミックスイン。"""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def pg_enum(enum_cls: type[_EnumT]) -> SAEnum:
    """str ベースの Enum を「VARCHAR(32) に *値* を保存する」共通カラム型として返す。

    DRY 目的の共通ファクトリ。``native_enum=False`` で PostgreSQL の ENUM 型を使わず
    VARCHAR で表現し、分類体系の拡張時に ``ALTER TYPE`` を不要にする（ハンドオフ §6 で
    カテゴリ体系の拡張が想定されているため）。``values_callable`` により Enum の
    ``name`` ではなく ``value`` を永続化する。

    Args:
        enum_cls: ``str`` を継承した ``enum.Enum`` のサブクラス。

    Returns:
        設定済みの :class:`sqlalchemy.Enum` インスタンス。
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )
