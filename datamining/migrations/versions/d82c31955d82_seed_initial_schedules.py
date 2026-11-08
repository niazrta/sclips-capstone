"""seed initial schedules

Revision ID: d82c31955d82
Revises: 4b1759ea356c
Create Date: 2026-11-08 21:07:21.009278

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd82c31955d82'
down_revision: Union[str, Sequence[str], None] = '4b1759ea356c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
        INSERT INTO sync_schedules (name, scope, frequency, weekdays, run_time, timezone, is_active)
        VALUES ('Cek harian jurnal baru', 'new', 'daily', NULL, '02:00', 'Asia/Jakarta', false),
               ('Sinkron penuh mingguan', 'full', 'weekly', ARRAY[5], '02:00', 'Asia/Jakarta', false)
    """)


def downgrade():
    op.execute("DELETE FROM sync_schedules WHERE name IN ('Cek harian jurnal baru','Sinkron penuh mingguan')")