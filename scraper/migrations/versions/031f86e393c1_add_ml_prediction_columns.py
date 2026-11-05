"""add ml prediction columns

Revision ID: 031f86e393c1
Revises: a958ab7a3fc7
Create Date: 2026-11-05 07:11:57.942299

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '031f86e393c1'
down_revision: Union[str, Sequence[str], None] = 'a958ab7a3fc7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JOURNAL_COLS = [
    ("predicted_subject_sinta", sa.String()),
    ("predicted_subject_sinta_multilabel", sa.String()),
    ("predicted_subject_scopus", sa.String()),
    ("predicted_subject_scopus_27", sa.String()),
    ("scopus_confidence", sa.Numeric(6, 3)),
    ("predictions_updated_at", sa.DateTime(timezone=True)),
]
PUBLISHER_COLS = [
    ("publisher_size", sa.String()),
    ("type_confidence", sa.Numeric(6, 3)),
]


def upgrade():
    for n, t in JOURNAL_COLS:
        op.add_column("journals", sa.Column(n, t, nullable=True))
    for n, t in PUBLISHER_COLS:
        op.add_column("publishers", sa.Column(n, t, nullable=True))
    op.execute("""
        CREATE VIEW journals_public AS
        SELECT j.*,
               COALESCE(j.subject, j.predicted_subject_sinta_multilabel) AS subject_display,
               CASE WHEN j.subject IS NOT NULL THEN 'sinta'
                    WHEN j.predicted_subject_sinta_multilabel IS NOT NULL THEN 'ml'
               END AS subject_source
        FROM journals j
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS journals_public")
    for n, _ in PUBLISHER_COLS:
        op.drop_column("publishers", n)
    for n, _ in JOURNAL_COLS:
        op.drop_column("journals", n)