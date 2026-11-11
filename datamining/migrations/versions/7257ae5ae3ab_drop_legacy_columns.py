"""drop legacy columns

Revision ID: 7257ae5ae3ab
Revises: d82c31955d82
Create Date: 2026-11-08 23:03:26.234259

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7257ae5ae3ab'
down_revision: Union[str, Sequence[str], None] = 'd82c31955d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


VIEW_SQL = """
    CREATE VIEW journals_public AS
    SELECT j.*,
           COALESCE(j.subject, j.predicted_subject_sinta_multilabel) AS subject_display,
           CASE WHEN j.subject IS NOT NULL THEN 'sinta'
                WHEN j.predicted_subject_sinta_multilabel IS NOT NULL THEN 'ml'
           END AS subject_source
    FROM journals j
"""
GRANT_SQL = """
    DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fullstack_reader') THEN
        GRANT SELECT ON journals_public TO fullstack_reader;
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fullstack_admin') THEN
        GRANT SELECT ON journals_public TO fullstack_admin;
      END IF;
    END $$;
"""


def upgrade():
    op.execute("DROP VIEW IF EXISTS journals_public")
    op.drop_column("journals", "sinta_url")
    op.drop_column("journals", "current_rank")
    op.drop_column("publishers", "raw_name")
    op.execute(VIEW_SQL)
    op.execute(GRANT_SQL)


def downgrade():
    op.execute("DROP VIEW IF EXISTS journals_public")
    op.add_column("publishers", sa.Column("raw_name", sa.String(), nullable=True))
    op.add_column("journals", sa.Column("current_rank", sa.String(), nullable=True))
    op.add_column("journals", sa.Column("sinta_url", sa.String(), nullable=True))
    op.execute(VIEW_SQL)
    op.execute(GRANT_SQL)
