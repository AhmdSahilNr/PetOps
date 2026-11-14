"""first vertical slice schema

Revision ID: 0001
Revises: 
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

role_enum = sa.Enum("CUSTOMER", "STAFF", "ADMIN", name="role_enum")
service_type_enum = sa.Enum("GROOMING", "BOARDING", name="service_type_enum")
booking_type_enum = sa.Enum("GROOMING", "BOARDING", name="booking_type_enum")
booking_status_enum = sa.Enum("SUBMITTED", "CONFIRMED", "REJECTED", "CANCELLED", "IN_PROGRESS", "CHECKED_IN", "STAYING", "CHECKED_OUT", "COMPLETED", name="booking_status_enum")
event_old_status_enum = sa.Enum("SUBMITTED", "CONFIRMED", "REJECTED", "CANCELLED", "IN_PROGRESS", "CHECKED_IN", "STAYING", "CHECKED_OUT", "COMPLETED", name="event_old_status_enum")
event_new_status_enum = sa.Enum("SUBMITTED", "CONFIRMED", "REJECTED", "CANCELLED", "IN_PROGRESS", "CHECKED_IN", "STAYING", "CHECKED_OUT", "COMPLETED", name="event_new_status_enum")


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table("user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table("customers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table("pets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), sa.ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "id", name="uq_pet_customer_id"),
    )
    op.create_index("ix_pets_customer_id", "pets", ["customer_id"])
    op.create_table("services",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("service_type", service_type_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", "service_type", name="uq_service_name_type"),
    )
    op.create_table("bookings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("pet_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("booking_type", booking_type_enum, nullable=False),
        sa.Column("status", booking_status_enum, nullable=False),
        sa.Column("grooming_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("boarding_start", sa.Date(), nullable=True),
        sa.Column("boarding_end", sa.Date(), nullable=True),
        sa.Column("assigned_staff_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id", "pet_id"], ["pets.customer_id", "pets.id"], ondelete="RESTRICT", name="fk_booking_owned_pet"),
        sa.CheckConstraint("(booking_type = 'GROOMING' AND grooming_start IS NOT NULL AND boarding_start IS NULL AND boarding_end IS NULL) OR (booking_type = 'BOARDING' AND grooming_start IS NULL AND boarding_start IS NOT NULL AND boarding_end IS NOT NULL AND boarding_end > boarding_start)", name="ck_booking_schedule_shape"),
    )
    op.create_index("ix_bookings_customer_id", "bookings", ["customer_id"])
    op.create_index("ix_bookings_pet_id", "bookings", ["pet_id"])
    op.create_index("ix_bookings_assigned_staff_user_id", "bookings", ["assigned_staff_user_id"])
    op.create_index("ix_booking_customer_status", "bookings", ["customer_id", "status"])
    op.create_table("booking_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("booking_id", sa.Uuid(), sa.ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("old_status", event_old_status_enum, nullable=True),
        sa.Column("new_status", event_new_status_enum, nullable=True),
        sa.Column("old_schedule", sa.JSON(), nullable=True),
        sa.Column("new_schedule", sa.JSON(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_booking_events_booking_id", "booking_events", ["booking_id"])


def downgrade():
    op.drop_table("booking_events")
    op.drop_table("bookings")
    op.drop_table("services")
    op.drop_table("pets")
    op.drop_table("customers")
    op.drop_table("user_sessions")
    op.drop_table("users")
