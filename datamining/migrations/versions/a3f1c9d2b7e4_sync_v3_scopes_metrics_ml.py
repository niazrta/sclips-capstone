"""sync v3: dua cakupan, pengukuran run, hasil ML

Revision ID: a3f1c9d2b7e4
Revises: 7257ae5ae3ab
Create Date: 2026-11-10 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3f1c9d2b7e4"
down_revision: Union[str, None] = "7257ae5ae3ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOURNAL_COLS = [
    ("predicted_status", sa.String()),
    ("predicted_review_reasons", sa.Text()),
    ("predicted_model_version", sa.String()),
]
RUN_COLS = [
    ("run_ml_predict", sa.Boolean(), {"nullable": False, "server_default": sa.text("false")}),
    ("duration_seconds", sa.Numeric(10, 1), {}),
    ("http_requests", sa.Integer(), {}),
    ("bytes_downloaded", sa.BigInteger(), {}),
    ("cpu_avg_percent", sa.Numeric(6, 1), {}),
    ("cpu_peak_percent", sa.Numeric(6, 1), {}),
    ("ram_peak_mb", sa.Numeric(10, 1), {}),
    ("db_size_mb", sa.Numeric(10, 1), {}),
    ("host_info", sa.Text(), {}),
]


def upgrade() -> None:
    for name, typ in JOURNAL_COLS:
        op.add_column("journals", sa.Column(name, typ, nullable=True))
    for name, typ, kw in RUN_COLS:
        op.add_column("sync_runs", sa.Column(name, typ, **({"nullable": True} | kw)))
    # cakupan 'new' dihapus: jadwal harian lama menjadi 'update'
    op.execute("UPDATE sync_schedules SET scope='update', name='Update harian' "
               "WHERE scope='new' AND name='Cek harian jurnal baru'")
    op.execute("UPDATE sync_schedules SET scope='update' WHERE scope='new'")


def downgrade() -> None:
    for name, *_ in reversed(RUN_COLS):
        op.drop_column("sync_runs", name)
    for name, _ in reversed(JOURNAL_COLS):
        op.drop_column("journals", name)
    op.execute("UPDATE sync_schedules SET scope='new', name='Cek harian jurnal baru' "
               "WHERE scope='update' AND name='Update harian'")
