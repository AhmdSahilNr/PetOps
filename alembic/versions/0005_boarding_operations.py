"""Boarding operations with retained capacity and history.

Revision ID: 0005
Revises: 0004
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_context().dialect.name == "postgresql"
    if pg:
        op.execute("""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM bookings WHERE booking_type='BOARDING'
              AND status IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED')) THEN
            RAISE EXCEPTION '0005: legacy operational Boarding rows need reviewed repair; stay history will not be fabricated';
          END IF;
        END $$""")
    with op.batch_alter_table("boarding_allocations") as b:
        b.create_unique_constraint("uq_allocation_booking_id", ["booking_id", "id"])
    columns = [sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("booking_id", sa.Uuid(), sa.ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("allocation_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("checked_in_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False)]
    for step in ("stay_started", "checked_out", "completed"):
        columns.extend([sa.Column(step+"_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
                        sa.Column(step+"_at", sa.DateTime(timezone=True), nullable=True)])
    op.create_table("boarding_stays", *columns,
        sa.ForeignKeyConstraint(["booking_id", "allocation_id"], ["boarding_allocations.booking_id", "boarding_allocations.id"], name="fk_stay_owned_allocation", ondelete="RESTRICT"),
        sa.CheckConstraint("(stay_started_at IS NULL AND stay_started_by_user_id IS NULL) OR (stay_started_at IS NOT NULL AND stay_started_by_user_id IS NOT NULL AND stay_started_at >= checked_in_at)", name="ck_stay_started"),
        sa.CheckConstraint("(checked_out_at IS NULL AND checked_out_by_user_id IS NULL) OR (checked_out_at IS NOT NULL AND checked_out_by_user_id IS NOT NULL AND stay_started_at IS NOT NULL AND checked_out_at >= stay_started_at)", name="ck_stay_checkout"),
        sa.CheckConstraint("(completed_at IS NULL AND completed_by_user_id IS NULL) OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL AND checked_out_at IS NOT NULL AND completed_at >= checked_out_at)", name="ck_stay_completion"))
    for step in ("checked_in", "stay_started", "checked_out", "completed"):
        op.create_index("ix_boarding_stays_"+step+"_by_user_id", "boarding_stays", [step+"_by_user_id"])
    op.create_table("boarding_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("stay_id", sa.Uuid(), sa.ForeignKey("boarding_stays.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("booking_events.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(note)) BETWEEN 1 AND 4000 AND note = trim(note)", name="ck_boarding_note"))
    for column in ("stay_id", "actor_user_id"):
        op.create_index("ix_boarding_notes_"+column, "boarding_notes", [column])
    predicate=sa.text("event_type IN ('BOARDING_CHECKED_IN','BOARDING_STAY_STARTED','BOARDING_CHECKED_OUT','BOARDING_COMPLETED')")
    op.create_index("uq_boarding_lifecycle_event", "booking_events", ["booking_id", "event_type"], unique=True,
                    postgresql_where=predicate, sqlite_where=predicate)
    if pg:
        op.execute(Path(__file__).with_name("0005_rules.sql").read_text(encoding="utf-8"))


def downgrade():
    raise RuntimeError("0005 retains stay and capacity history; use reviewed forward repair or backup restore")
