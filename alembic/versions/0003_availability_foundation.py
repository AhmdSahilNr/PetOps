"""Slice 2 availability, capacity and confirmation prerequisites.

Revision ID: 0003
Revises: 0002
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_context().dialect.name == "postgresql"
    role = postgresql.ENUM("CUSTOMER", "STAFF", "ADMIN", name="role_enum", create_type=False) if pg else sa.String(8)
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("scheduling_version", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("services") as b:
        b.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
        b.add_column(sa.Column("updated_by_user_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        b.create_foreign_key("fk_service_config_actor", "users", ["updated_by_user_id"], ["id"], ondelete="RESTRICT")
        b.create_check_constraint("ck_service_duration", "(service_type = 'GROOMING' AND (duration_minutes IS NULL OR duration_minutes > 0)) OR (service_type = 'BOARDING' AND duration_minutes IS NULL)")
    with op.batch_alter_table("bookings") as b:
        b.add_column(sa.Column("grooming_duration_minutes", sa.Integer(), nullable=True))
        b.add_column(sa.Column("staff_start", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("staff_end", sa.DateTime(timezone=True), nullable=True))
        b.create_check_constraint("ck_booking_duration", "(booking_type = 'GROOMING' AND (grooming_duration_minutes IS NULL OR grooming_duration_minutes > 0)) OR (booking_type = 'BOARDING' AND grooming_duration_minutes IS NULL)")
        b.create_check_constraint("ck_booking_staff_window", "(staff_start IS NULL AND staff_end IS NULL) OR (assigned_staff_user_id IS NOT NULL AND staff_start IS NOT NULL AND staff_end IS NOT NULL AND staff_end > staff_start)")
    op.add_column("booking_events", sa.Column("details", sa.JSON(), nullable=True))
    op.create_table("staff_availability",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("staff_user_id", sa.Uuid(), nullable=False),
        sa.Column("staff_role", role, nullable=False, server_default="STAFF"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["staff_user_id", "staff_role"], ["users.id", "users.role"], ondelete="RESTRICT", name="fk_availability_staff_role"),
        sa.CheckConstraint("staff_role = 'STAFF' AND ends_at > starts_at", name="ck_availability_window"))
    op.create_index("ix_staff_availability_staff_user_id", "staff_availability", ["staff_user_id"])
    op.create_table("accommodations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reservation_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capacity > 0", name="ck_accommodation_capacity"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 120 AND name = trim(name) AND length(trim(category)) BETWEEN 1 AND 120 AND category = trim(category)", name="ck_accommodation_name"))
    op.create_table("boarding_allocations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("booking_id", sa.Uuid(), sa.ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("accommodation_id", sa.Uuid(), sa.ForeignKey("accommodations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.CheckConstraint("ends_on > starts_on", name="ck_allocation_dates"),
        sa.CheckConstraint("(released_at IS NULL AND released_by_user_id IS NULL) OR (released_at IS NOT NULL AND released_by_user_id IS NOT NULL AND released_at >= created_at)", name="ck_allocation_release"))
    op.create_index("ix_boarding_allocations_accommodation_id", "boarding_allocations", ["accommodation_id"])
    op.create_index("uq_current_booking_allocation", "boarding_allocations", ["booking_id"], unique=True,
                    postgresql_where=sa.text("released_at IS NULL"), sqlite_where=sa.text("released_at IS NULL"))
    if pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute("""ALTER TABLE bookings ADD CONSTRAINT ex_booking_staff_overlap
            EXCLUDE USING gist (assigned_staff_user_id WITH =, tstzrange(staff_start,staff_end,'[)') WITH &&)
            WHERE (assigned_staff_user_id IS NOT NULL AND staff_start IS NOT NULL
            AND status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING'))""")
        op.execute(Path(__file__).with_name("0003_rules.sql").read_text(encoding="utf-8"))


def downgrade():
    raise RuntimeError("0003 preserves resource/history integrity; use a reviewed forward repair or backup restore")
