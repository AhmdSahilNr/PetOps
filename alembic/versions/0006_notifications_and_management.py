"""In-system notices, explicit reminder configuration and management audit.

Revision ID: 0006
Revises: 0005
"""
from pathlib import Path
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="0006"
down_revision="0005"
branch_labels=None
depends_on=None
KINDS="'BOOKING_SUBMITTED','BOOKING_CONFIRMED','BOOKING_REJECTED','BOOKING_RESCHEDULED','BOOKING_RECONFIRMED','RESCHEDULE_REJECTED','BOOKING_CANCELLED','STAFF_ASSIGNED','STAFF_REASSIGNED','BOOKING_REMINDER'"


def upgrade():
    pg=op.get_context().dialect.name=="postgresql"
    role=postgresql.ENUM("CUSTOMER","STAFF","ADMIN",name="role_enum",create_type=False) if pg else sa.String(8)
    with op.batch_alter_table("booking_events") as b:
        b.create_unique_constraint("uq_event_booking_id",["booking_id","id"])
    op.create_table("notification_settings",
        sa.Column("id",sa.Integer(),primary_key=True,server_default="1"),
        sa.Column("enabled",sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column("lead_minutes",sa.Integer(),nullable=True),
        sa.Column("updated_by_user_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=True),
        sa.Column("updated_at",sa.DateTime(timezone=True),nullable=True),
        sa.CheckConstraint("id = 1",name="ck_notification_setting_singleton"),
        sa.CheckConstraint("(lead_minutes IS NULL OR lead_minutes BETWEEN 1 AND 525600) AND (NOT enabled OR lead_minutes IS NOT NULL)",name="ck_notification_lead"),
        sa.CheckConstraint("(updated_by_user_id IS NULL AND updated_at IS NULL) OR (updated_by_user_id IS NOT NULL AND updated_at IS NOT NULL)",name="ck_notification_setting_actor"))
    op.execute("INSERT INTO notification_settings(id,enabled) VALUES (1,false)")
    op.create_table("notifications",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("recipient_user_id",sa.Uuid(),nullable=False),
        sa.Column("recipient_role",role,nullable=False),
        sa.Column("booking_id",sa.Uuid(),sa.ForeignKey("bookings.id",ondelete="RESTRICT"),nullable=False),
        sa.Column("source_event_id",sa.Uuid(),nullable=False),
        sa.Column("kind",sa.String(40),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.Column("read_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("schedule_reference",sa.DateTime(timezone=True),nullable=True),
        sa.Column("lead_minutes",sa.Integer(),nullable=True),
        sa.ForeignKeyConstraint(["recipient_user_id","recipient_role"],["users.id","users.role"],name="fk_notification_recipient_role",ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["booking_id","source_event_id"],["booking_events.booking_id","booking_events.id"],name="fk_notification_booking_event",ondelete="RESTRICT"),
        sa.UniqueConstraint("recipient_user_id","source_event_id","kind",name="uq_notification_event_recipient_kind"),
        sa.CheckConstraint("recipient_role IN ('CUSTOMER','STAFF')",name="ck_notification_recipient"),
        sa.CheckConstraint("kind IN ("+KINDS+")",name="ck_notification_kind"),
        sa.CheckConstraint("read_at IS NULL OR read_at >= created_at",name="ck_notification_read_time"),
        sa.CheckConstraint("(kind = 'BOOKING_REMINDER' AND schedule_reference IS NOT NULL AND lead_minutes IS NOT NULL AND lead_minutes BETWEEN 1 AND 525600) OR (kind <> 'BOOKING_REMINDER' AND schedule_reference IS NULL AND lead_minutes IS NULL)",name="ck_notification_reminder_shape"))
    for column in ("booking_id","source_event_id"):op.create_index("ix_notifications_"+column,"notifications",[column])
    op.create_index("ix_notification_inbox","notifications",["recipient_user_id","created_at","id"])
    op.create_table("management_events",
        sa.Column("id",sa.Uuid(),primary_key=True),
        sa.Column("actor_user_id",sa.Uuid(),nullable=False),
        sa.Column("actor_role",role,nullable=False,server_default="ADMIN"),
        sa.Column("action",sa.String(40),nullable=False),
        sa.Column("staff_user_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="RESTRICT"),nullable=True),
        sa.Column("service_id",sa.Uuid(),sa.ForeignKey("services.id",ondelete="RESTRICT"),nullable=True),
        sa.Column("notification_setting_id",sa.Integer(),sa.ForeignKey("notification_settings.id",ondelete="RESTRICT"),nullable=True),
        sa.Column("details",sa.JSON(),nullable=False),
        sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id","actor_role"],["users.id","users.role"],name="fk_management_actor_role",ondelete="RESTRICT"),
        sa.CheckConstraint("actor_role = 'ADMIN'",name="ck_management_actor"),
        sa.CheckConstraint("(action IN ('STAFF_CREATED','STAFF_UPDATED') AND staff_user_id IS NOT NULL AND service_id IS NULL AND notification_setting_id IS NULL) OR (action IN ('SERVICE_CREATED','SERVICE_UPDATED') AND service_id IS NOT NULL AND staff_user_id IS NULL AND notification_setting_id IS NULL) OR (action = 'REMINDER_SETTINGS_UPDATED' AND notification_setting_id IS NOT NULL AND staff_user_id IS NULL AND service_id IS NULL)",name="ck_management_target"))
    for column in ("actor_user_id","staff_user_id","service_id"):op.create_index("ix_management_events_"+column,"management_events",[column])
    if pg:op.execute(Path(__file__).with_name("0006_rules.sql").read_text(encoding="utf-8"))


def downgrade():
    raise RuntimeError("0006 retains delivered notice/audit history; use reviewed forward repair or backup restore")
