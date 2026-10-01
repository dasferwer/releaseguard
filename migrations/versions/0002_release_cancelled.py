"""Добавляем терминальное состояние отмены до deploy."""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Новое значение используется приложением только после commit миграции.
    op.execute("ALTER TYPE release_status ADD VALUE IF NOT EXISTS 'cancelled'")


def downgrade() -> None:
    raise RuntimeError("Нельзя потерять отменённые релизы; восстановите согласованную копию БД")
