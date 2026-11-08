"""use sinta id as journal pk

Revision ID: 4888234ab98a
Revises: 8369a7b4a88c
Create Date: 2026-11-02 14:08:57.334349

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4888234ab98a'
down_revision: Union[str, Sequence[str], None] = '8369a7b4a88c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    conn = op.get_bind()

    bad = conn.execute(sa.text(
        "SELECT COUNT(*) FROM journals "
        "WHERE sinta_url IS NULL OR sinta_url !~ '/journals/profile/[0-9]+/?$'"
    )).scalar()
    if bad:
        raise RuntimeError(f"{bad} jurnal punya sinta_url tidak valid, migration dibatalkan")

    dup = conn.execute(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT substring(sinta_url from '([0-9]+)/?$') AS sid
            FROM journals GROUP BY 1 HAVING COUNT(*) > 1
        ) d
    """)).scalar()
    if dup:
        raise RuntimeError(f"{dup} ID SINTA ganda, migration dibatalkan")

    # tabel pemetaan ID lama -> ID SINTA (jangan dihapus, dipakai untuk ML/FS)
    op.execute("""
        CREATE TABLE journal_id_map AS
        SELECT id AS old_id,
               substring(sinta_url from '([0-9]+)/?$')::bigint AS sinta_id
        FROM journals
    """)
    op.execute("ALTER TABLE journal_id_map ADD PRIMARY KEY (old_id)")

    op.execute("ALTER TABLE journal_rank_histories DROP CONSTRAINT IF EXISTS journal_rank_histories_journal_id_fkey")
    op.execute("""
        UPDATE journal_rank_histories h SET journal_id = m.sinta_id
        FROM journal_id_map m WHERE h.journal_id = m.old_id
    """)
    op.execute("UPDATE journals SET id = -id")
    op.execute("""
        UPDATE journals j SET id = m.sinta_id
        FROM journal_id_map m WHERE j.id = -m.old_id
    """)
    op.execute("ALTER TABLE journals ALTER COLUMN id DROP DEFAULT")
    op.execute("""
        ALTER TABLE journal_rank_histories
        ADD CONSTRAINT journal_rank_histories_journal_id_fkey
        FOREIGN KEY (journal_id) REFERENCES journals(id)
    """)
    op.execute("""
        ALTER TABLE journal_rank_histories
        ADD CONSTRAINT uq_journal_year UNIQUE (journal_id, accreditation_year)
    """)
    op.execute("ALTER TABLE publishers ADD COLUMN sinta_publisher_id bigint")


def downgrade():
    raise NotImplementedError("Rollback lewat restore backup (pg_restore)")