"""add sync tables

Revision ID: 1373c47c7a3e
Revises: 031f86e393c1
Create Date: 2026-11-05 08:08:15.860678

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1373c47c7a3e'
down_revision: Union[str, Sequence[str], None] = '031f86e393c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.add_column("journals", sa.Column("last_detail_scraped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("journal_rank_histories", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE journal_rank_histories SET updated_at = scraped_at")

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_type", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("sinta_total", sa.Integer()),
        sa.Column("db_total_before", sa.Integer()),
        sa.Column("total_processed", sa.Integer(), server_default="0"),
        sa.Column("total_inserted", sa.Integer(), server_default="0"),
        sa.Column("total_updated", sa.Integer(), server_default="0"),
        sa.Column("total_skipped", sa.Integer(), server_default="0"),
        sa.Column("total_flagged", sa.Integer(), server_default="0"),
        sa.Column("pages_failed", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # hanya satu run aktif (queued atau running) pada satu waktu
    op.execute("""
        CREATE UNIQUE INDEX uq_one_active_sync_run ON sync_runs ((true))
        WHERE status IN ('queued', 'running')
    """)

    op.create_table(
        "sync_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("auto_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("frequency", sa.String(), nullable=False, server_default="weekly"),
        sa.Column("run_day", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("run_hour", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("detail_refresh_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_sync_settings_single_row"),
        sa.CheckConstraint("frequency IN ('weekly','monthly')", name="ck_sync_settings_frequency"),
        sa.CheckConstraint("run_day BETWEEN 0 AND 6", name="ck_sync_settings_day"),
        sa.CheckConstraint("run_hour BETWEEN 0 AND 23", name="ck_sync_settings_hour"),
    )
    op.execute("INSERT INTO sync_settings (id) VALUES (1)")


def downgrade():
    op.drop_table("sync_settings")
    op.execute("DROP INDEX IF EXISTS uq_one_active_sync_run")
    op.drop_table("sync_runs")
    op.drop_column("journal_rank_histories", "updated_at")
    op.drop_column("journals", "last_detail_scraped_at")