"""sync v2 schedules changes issn status

Revision ID: 4b1759ea356c
Revises: 1373c47c7a3e
Create Date: 2026-11-05 14:06:47.875312

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4b1759ea356c'
down_revision: Union[str, Sequence[str], None] = '1373c47c7a3e'
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
    END $$;
"""


def upgrade():
    op.execute("DROP VIEW IF EXISTS journals_public")

    # journals
    op.add_column("journals", sa.Column("e_issn_status", sa.String()))
    op.add_column("journals", sa.Column("p_issn_status", sa.String()))
    op.add_column("journals", sa.Column("sinta_affiliation_id", sa.BigInteger()))
    op.create_check_constraint("ck_journals_e_issn_status", "journals",
                               "e_issn_status IN ('valid','short','invalid','none')")
    op.create_check_constraint("ck_journals_p_issn_status", "journals",
                               "p_issn_status IN ('valid','short','invalid','none')")

    # sync_runs: run_type menjadi scope (tabel kosong, sudah dicek)
    op.alter_column("sync_runs", "run_type", new_column_name="scope")
    op.create_check_constraint("ck_sync_runs_scope", "sync_runs",
                               "scope IN ('new','update','full')")
    op.add_column("sync_runs", sa.Column("source", sa.String()))
    op.add_column("sync_runs", sa.Column("requested_by", sa.String()))
    op.add_column("sync_runs", sa.Column("target_id", sa.BigInteger()))

    # sync_schedules menggantikan sync_settings
    op.drop_table("sync_settings")
    op.create_table(
        "sync_schedules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("weekdays", postgresql.ARRAY(sa.Integer())),
        sa.Column("month_day", sa.Integer()),
        sa.Column("run_date", sa.Date()),
        sa.Column("cron_expr", sa.String()),
        sa.Column("run_time", sa.Time(), nullable=False, server_default="02:00"),
        sa.Column("timezone", sa.String(), nullable=False, server_default="Asia/Jakarta"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("after_ml_predict", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("after_reclassify_publisher", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("scope IN ('new','update','full')", name="ck_sync_schedules_scope"),
        sa.CheckConstraint("frequency IN ('daily','weekly','monthly','date','cron')",
                           name="ck_sync_schedules_frequency"),
        sa.CheckConstraint(
            "(frequency <> 'weekly' OR weekdays IS NOT NULL)"
            " AND (frequency <> 'monthly' OR (month_day IS NOT NULL AND month_day BETWEEN 1 AND 31))"
            " AND (frequency <> 'date' OR run_date IS NOT NULL)"
            " AND (frequency <> 'cron' OR cron_expr IS NOT NULL)",
            name="ck_sync_schedules_fields"),
    )

    # sync_changes
    op.create_table(
        "sync_changes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("sync_runs.id"), nullable=False),
        sa.Column("journal_id", sa.BigInteger(), sa.ForeignKey("journals.id"), nullable=False),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("old_value", sa.Text()),
        sa.Column("new_value", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_sync_changes_run", "sync_changes", ["run_id"])
    op.create_index("ix_sync_changes_journal", "sync_changes", ["journal_id"])

    # view dibuat ulang supaya kolom baru ikut muncul
    op.execute(VIEW_SQL)
    op.execute(GRANT_SQL)


def downgrade():
    op.execute("DROP VIEW IF EXISTS journals_public")
    op.drop_table("sync_changes")
    op.drop_table("sync_schedules")
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
    )
    op.execute("INSERT INTO sync_settings (id) VALUES (1)")
    op.drop_column("sync_runs", "target_id")
    op.drop_column("sync_runs", "requested_by")
    op.drop_column("sync_runs", "source")
    op.drop_constraint("ck_sync_runs_scope", "sync_runs", type_="check")
    op.alter_column("sync_runs", "scope", new_column_name="run_type")
    op.drop_constraint("ck_journals_p_issn_status", "journals", type_="check")
    op.drop_constraint("ck_journals_e_issn_status", "journals", type_="check")
    op.drop_column("journals", "sinta_affiliation_id")
    op.drop_column("journals", "p_issn_status")
    op.drop_column("journals", "e_issn_status")
    op.execute(VIEW_SQL)
    op.execute(GRANT_SQL)