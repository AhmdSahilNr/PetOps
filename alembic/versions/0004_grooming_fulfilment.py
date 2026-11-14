"""Grooming fulfilment and retained completion evidence (forward-only).

Revision ID: 0004
Revises: 0003
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_context().dialect.name == "postgresql"
    if pg:
        op.execute("""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM bookings WHERE booking_type='GROOMING'
              AND status IN ('IN_PROGRESS','COMPLETED')) THEN
            RAISE EXCEPTION '0004: unexplained legacy operational Grooming records require reviewed repair; no history is fabricated';
          END IF;
        END $$""")
    op.create_table("grooming_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("booking_id", sa.Uuid(), sa.ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("started_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("service_notes", sa.Text(), nullable=True),
        sa.CheckConstraint("(completed_at IS NULL AND completed_by_user_id IS NULL AND service_notes IS NULL) OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL AND completed_at >= started_at)", name="ck_grooming_completion"),
        sa.CheckConstraint("service_notes IS NULL OR (length(trim(service_notes)) BETWEEN 1 AND 4000 AND service_notes = trim(service_notes))", name="ck_grooming_notes"))
    for column in ("started_by_user_id", "completed_by_user_id"):
        op.create_index("ix_grooming_records_" + column, "grooming_records", [column])
    predicate = sa.text("event_type IN ('GROOMING_STARTED','GROOMING_COMPLETED')")
    op.create_index("uq_grooming_lifecycle_event", "booking_events", ["booking_id", "event_type"], unique=True,
                    postgresql_where=predicate, sqlite_where=predicate)
    if pg:
        op.execute(Path(__file__).with_name("0004_rules.sql").read_text(encoding="utf-8"))


def downgrade():
    raise RuntimeError("0004 retains completion history; use reviewed forward repair or backup restore")
