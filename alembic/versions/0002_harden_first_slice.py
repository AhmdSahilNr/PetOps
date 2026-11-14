"""First-slice integrity, role links, concurrency and history retention.

Revision ID: 0002
Revises: 0001

Existing invalid data is deliberately rejected, never silently repaired/deleted.
PostgreSQL is the authoritative target; SQLite remains a test surrogate.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_context().dialect.name == "postgresql"
    role = postgresql.ENUM("CUSTOMER", "STAFF", "ADMIN", name="role_enum", create_type=False) if pg else sa.String(8)
    if pg:
        # The old CHECK embeds constants typed as booking_type_enum. Rebuild it
        # around the type conversion rather than leaving incompatible operators.
        op.drop_constraint("ck_booking_schedule_shape", "bookings", type_="check")
        op.alter_column("bookings", "booking_type",
                        type_=postgresql.ENUM("GROOMING", "BOARDING", name="service_type_enum", create_type=False),
                        postgresql_using="booking_type::text::service_type_enum")
        op.execute("DROP TYPE booking_type_enum")
        op.create_check_constraint("ck_booking_schedule_shape", "bookings",
            "(booking_type = 'GROOMING' AND grooming_start IS NOT NULL AND boarding_start IS NULL AND boarding_end IS NULL) OR "
            "(booking_type = 'BOARDING' AND grooming_start IS NULL AND boarding_start IS NOT NULL AND boarding_end IS NOT NULL AND boarding_end > boarding_start)")

    with op.batch_alter_table("users") as b:
        b.create_unique_constraint("uq_user_id_role", ["id", "role"])
        b.create_check_constraint("ck_user_email_normalized", "email = lower(trim(email)) AND length(email) BETWEEN 3 AND 320")
        b.create_check_constraint("ck_user_role", "role IN ('CUSTOMER','STAFF','ADMIN')")
    with op.batch_alter_table("user_sessions") as b:
        b.create_check_constraint("ck_session_expiry", "expires_at > created_at")
        b.create_check_constraint("ck_session_token_hash", "length(token_hash) = 64")
    with op.batch_alter_table("customers") as b:
        b.add_column(sa.Column("account_role", role, nullable=False, server_default="CUSTOMER"))
        b.create_unique_constraint("uq_customer_id_user", ["id", "user_id"])
        b.create_foreign_key("fk_customer_role", "users", ["user_id", "account_role"], ["id", "role"], ondelete="RESTRICT")
        b.create_check_constraint("ck_customer_role", "account_role = 'CUSTOMER'")
        b.create_check_constraint("ck_customer_name", "length(trim(display_name)) BETWEEN 1 AND 120 AND display_name = trim(display_name)")
    with op.batch_alter_table("pets") as b:
        b.create_check_constraint("ck_pet_name", "length(trim(name)) BETWEEN 1 AND 120 AND name = trim(name)")
    with op.batch_alter_table("services") as b:
        b.create_unique_constraint("uq_service_id_type", ["id", "service_type"])
        b.create_check_constraint("ck_service_name", "length(trim(name)) BETWEEN 1 AND 120 AND name = trim(name)")
        b.create_check_constraint("ck_service_type", "service_type IN ('GROOMING','BOARDING')")
    with op.batch_alter_table("bookings") as b:
        b.add_column(sa.Column("assigned_staff_role", role, nullable=False, server_default="STAFF"))
        b.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        b.create_foreign_key("fk_booking_service_type", "services", ["service_id", "booking_type"], ["id", "service_type"], ondelete="RESTRICT")
        b.create_foreign_key("fk_booking_customer_creator", "customers", ["customer_id", "created_by_user_id"], ["id", "user_id"], ondelete="RESTRICT")
        b.create_foreign_key("fk_booking_staff_role", "users", ["assigned_staff_user_id", "assigned_staff_role"], ["id", "role"], ondelete="RESTRICT")
        b.create_check_constraint("ck_booking_staff_role", "assigned_staff_role = 'STAFF'")
        b.create_check_constraint("ck_booking_version", "version > 0")
        b.create_check_constraint("ck_booking_type_status", "status IN ('SUBMITTED','CONFIRMED','REJECTED','CANCELLED','COMPLETED') OR (booking_type = 'GROOMING' AND status = 'IN_PROGRESS') OR (booking_type = 'BOARDING' AND status IN ('CHECKED_IN','STAYING','CHECKED_OUT'))")
        b.create_index("ix_bookings_service_id", ["service_id"])
        b.create_index("ix_bookings_created_by_user_id", ["created_by_user_id"])
    with op.batch_alter_table("booking_events") as b:
        b.add_column(sa.Column("old_assigned_staff_user_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("new_assigned_staff_user_id", sa.Uuid(), nullable=True))
        for side in ("old", "new"):
            field = f"{side}_assigned_staff_user_id"
            b.create_foreign_key(f"fk_event_{side}_staff", "users", [field], ["id"], ondelete="RESTRICT")
            b.create_index(f"ix_booking_events_{field}", [field])
        b.create_index("ix_booking_events_actor_user_id", ["actor_user_id"])
        b.create_index("ix_booking_event_chronology", ["booking_id", "created_at"])

    if pg:
        op.execute("""CREATE FUNCTION petops_preserve_booking_event() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'Booking history is append-only' USING ERRCODE = '23514';
        END; $$""")
        op.execute("""CREATE TRIGGER booking_event_append_only BEFORE UPDATE OR DELETE
        ON booking_events FOR EACH ROW EXECUTE FUNCTION petops_preserve_booking_event()""")


def downgrade():
    raise RuntimeError("0002 is forward-only: restore a reviewed backup rather than remove integrity/history safeguards")
