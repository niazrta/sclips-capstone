"""add listing fields

Revision ID: a958ab7a3fc7
Revises: 4888234ab98a
Create Date: 2026-11-02 23:18:45.441988

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a958ab7a3fc7'
down_revision: Union[str, Sequence[str], None] = '4888234ab98a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("journals", sa.Column("website", sa.Text(), nullable=True))
    op.add_column("journals", sa.Column("editor_url", sa.Text(), nullable=True))
    op.add_column("journals", sa.Column("google_scholar_url", sa.Text(), nullable=True))
    op.add_column("journals", sa.Column("garuda_id", sa.BigInteger(), nullable=True))
    op.add_column("journals", sa.Column("cover_url", sa.Text(), nullable=True))
    op.add_column("journals", sa.Column("rank_badge", sa.String(), nullable=True))
    op.add_column("journals", sa.Column("scopus_indexed", sa.Boolean(), nullable=True))
    op.add_column("journals", sa.Column("garuda_indexed", sa.Boolean(), nullable=True))
    op.add_column("journals", sa.Column("impact", sa.Numeric(10, 2), nullable=True))
    op.add_column("journals", sa.Column("h5_index", sa.Integer(), nullable=True))
    op.add_column("journals", sa.Column("citations_5yr", sa.Integer(), nullable=True))
    op.add_column("journals", sa.Column("citations", sa.Integer(), nullable=True))
    op.add_column("journals", sa.Column("metrics_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("journals", "metrics_updated_at")
    op.drop_column("journals", "citations")
    op.drop_column("journals", "citations_5yr")
    op.drop_column("journals", "h5_index")
    op.drop_column("journals", "impact")
    op.drop_column("journals", "garuda_indexed")
    op.drop_column("journals", "scopus_indexed")
    op.drop_column("journals", "rank_badge")
    op.drop_column("journals", "cover_url")
    op.drop_column("journals", "garuda_id")
    op.drop_column("journals", "google_scholar_url")
    op.drop_column("journals", "editor_url")
    op.drop_column("journals", "website")