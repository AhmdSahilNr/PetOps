from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, String, Text, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    CUSTOMER = "CUSTOMER"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


class ServiceType(str, enum.Enum):
    GROOMING = "GROOMING"
    BOARDING = "BOARDING"


class BookingStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    IN_PROGRESS = "IN_PROGRESS"
    CHECKED_IN = "CHECKED_IN"
    STAYING = "STAYING"
    CHECKED_OUT = "CHECKED_OUT"
    COMPLETED = "COMPLETED"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    scheduling_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    __table_args__ = (
        UniqueConstraint("id", "role", name="uq_user_id_role"),
        CheckConstraint("email = lower(trim(email)) AND length(email) BETWEEN 3 AND 320", name="ck_user_email_normalized"),
        CheckConstraint("role IN ('CUSTOMER', 'STAFF', 'ADMIN')", name="ck_user_role"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_session_expiry"),
        CheckConstraint("length(token_hash) = 64", name="ck_session_token_hash"),
    )


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True)
    account_role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), nullable=False, default=Role.CUSTOMER, server_default="CUSTOMER")
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_customer_id_user"),
        ForeignKeyConstraint(["user_id", "account_role"], ["users.id", "users.role"], name="fk_customer_role", ondelete="RESTRICT"),
        CheckConstraint("account_role = 'CUSTOMER'", name="ck_customer_role"),
        CheckConstraint("length(trim(display_name)) BETWEEN 1 AND 120 AND display_name = trim(display_name)", name="ck_customer_name"),
    )


class Pet(Base):
    __tablename__ = "pets"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("customer_id", "id", name="uq_pet_customer_id"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120 AND name = trim(name)", name="ck_pet_name"),
    )


class Service(Base):
    __tablename__ = "services"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    service_type: Mapped[ServiceType] = mapped_column(Enum(ServiceType, name="service_type_enum"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=utcnow)
    __table_args__ = (
        UniqueConstraint("name", "service_type", name="uq_service_name_type"),
        UniqueConstraint("id", "service_type", name="uq_service_id_type"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120 AND name = trim(name)", name="ck_service_name"),
        CheckConstraint("service_type IN ('GROOMING', 'BOARDING')", name="ck_service_type"),
        CheckConstraint("(service_type = 'GROOMING' AND (duration_minutes IS NULL OR duration_minutes > 0)) OR (service_type = 'BOARDING' AND duration_minutes IS NULL)", name="ck_service_duration"),
    )


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    pet_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=False)
    booking_type: Mapped[ServiceType] = mapped_column(Enum(ServiceType, name="service_type_enum"), nullable=False)
    status: Mapped[BookingStatus] = mapped_column(Enum(BookingStatus, name="booking_status_enum"), nullable=False, default=BookingStatus.SUBMITTED)
    grooming_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grooming_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    boarding_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    boarding_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    assigned_staff_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    assigned_staff_role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), nullable=False, default=Role.STAFF, server_default="STAFF")
    staff_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    staff_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        CheckConstraint("(booking_type = 'GROOMING' AND (grooming_duration_minutes IS NULL OR grooming_duration_minutes > 0)) OR (booking_type = 'BOARDING' AND grooming_duration_minutes IS NULL)", name="ck_booking_duration"),
        CheckConstraint("(staff_start IS NULL AND staff_end IS NULL) OR (assigned_staff_user_id IS NOT NULL AND staff_start IS NOT NULL AND staff_end IS NOT NULL AND staff_end > staff_start)", name="ck_booking_staff_window"),
        ExcludeConstraint(("assigned_staff_user_id", "="), (text("tstzrange(staff_start, staff_end, '[)')"), "&&"),
            where=text("assigned_staff_user_id IS NOT NULL AND staff_start IS NOT NULL AND status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING')"),
            name="ex_booking_staff_overlap", using="gist").ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(["service_id", "booking_type"], ["services.id", "services.service_type"], name="fk_booking_service_type", ondelete="RESTRICT"),
        ForeignKeyConstraint(["customer_id", "created_by_user_id"], ["customers.id", "customers.user_id"], name="fk_booking_customer_creator", ondelete="RESTRICT"),
        ForeignKeyConstraint(["assigned_staff_user_id", "assigned_staff_role"], ["users.id", "users.role"], name="fk_booking_staff_role", ondelete="RESTRICT"),
        CheckConstraint("assigned_staff_role = 'STAFF'", name="ck_booking_staff_role"),
        CheckConstraint("version > 0", name="ck_booking_version"),
        CheckConstraint("status IN ('SUBMITTED','CONFIRMED','REJECTED','CANCELLED','COMPLETED') OR (booking_type = 'GROOMING' AND status = 'IN_PROGRESS') OR (booking_type = 'BOARDING' AND status IN ('CHECKED_IN','STAYING','CHECKED_OUT'))", name="ck_booking_type_status"),
        ForeignKeyConstraint(["customer_id", "pet_id"], ["pets.customer_id", "pets.id"], ondelete="RESTRICT", name="fk_booking_owned_pet"),
        CheckConstraint(
            "(booking_type = 'GROOMING' AND grooming_start IS NOT NULL AND boarding_start IS NULL AND boarding_end IS NULL) OR "
            "(booking_type = 'BOARDING' AND grooming_start IS NULL AND boarding_start IS NOT NULL AND boarding_end IS NOT NULL AND boarding_end > boarding_start)",
            name="ck_booking_schedule_shape",
        ),
        Index("ix_booking_customer_status", "customer_id", "status"),
        Index("ix_bookings_service_id", "service_id"),
        Index("ix_bookings_created_by_user_id", "created_by_user_id"),
    )


class StaffResponsibility(Base):
    """Booking-linked planned accountability, with retained original period."""
    __tablename__ = "staff_responsibilities"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, index=True)
    staff_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        CheckConstraint("ends_at > starts_at AND (ended_at IS NULL OR (ended_at > starts_at AND ended_at <= ends_at AND ended_by_user_id IS NOT NULL))", name="ck_responsibility_period"),
        ExcludeConstraint(("staff_user_id", "="), (text("tstzrange(starts_at, coalesce(ended_at,ends_at), '[)')"), "&&"), where=text("released_at IS NULL"), name="ex_responsibility_staff_overlap", using="gist").ddl_if(dialect="postgresql"),
        ExcludeConstraint(("booking_id", "="), (text("tstzrange(starts_at, coalesce(ended_at,ends_at), '[)')"), "&&"), where=text("released_at IS NULL"), name="ex_responsibility_booking_overlap", using="gist").ddl_if(dialect="postgresql"),
    )


class BookingEvent(Base):
    __tablename__ = "booking_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    old_status: Mapped[BookingStatus | None] = mapped_column(Enum(BookingStatus, name="event_old_status_enum"), nullable=True)
    new_status: Mapped[BookingStatus | None] = mapped_column(Enum(BookingStatus, name="event_new_status_enum"), nullable=True)
    old_schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    old_assigned_staff_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    new_assigned_staff_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        UniqueConstraint("booking_id", "id", name="uq_event_booking_id"),
        Index("ix_booking_events_actor_user_id", "actor_user_id"),
        Index("ix_booking_event_chronology", "booking_id", "created_at"),
        Index("uq_grooming_lifecycle_event", "booking_id", "event_type", unique=True,
            postgresql_where=text("event_type IN ('GROOMING_STARTED','GROOMING_COMPLETED')"),
            sqlite_where=text("event_type IN ('GROOMING_STARTED','GROOMING_COMPLETED')")),
        Index("uq_boarding_lifecycle_event", "booking_id", "event_type", unique=True,
            postgresql_where=text("event_type IN ('BOARDING_CHECKED_IN','BOARDING_STAY_STARTED','BOARDING_CHECKED_OUT','BOARDING_COMPLETED')"),
            sqlite_where=text("event_type IN ('BOARDING_CHECKED_IN','BOARDING_STAY_STARTED','BOARDING_CHECKED_OUT','BOARDING_COMPLETED')")),
    )


class GroomingRecord(Base):
    __tablename__ = "grooming_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, unique=True)
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("(completed_at IS NULL AND completed_by_user_id IS NULL AND service_notes IS NULL) OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL AND completed_at >= started_at)", name="ck_grooming_completion"),
        CheckConstraint("service_notes IS NULL OR (length(trim(service_notes)) BETWEEN 1 AND 4000 AND service_notes = trim(service_notes))", name="ck_grooming_notes"),
    )


class BoardingStay(Base):
    __tablename__ = "boarding_stays"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, unique=True)
    allocation_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    checked_in_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    checked_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stay_started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    stay_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_out_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["booking_id", "allocation_id"], ["boarding_allocations.booking_id", "boarding_allocations.id"], name="fk_stay_owned_allocation", ondelete="RESTRICT"),
        CheckConstraint("(stay_started_at IS NULL AND stay_started_by_user_id IS NULL) OR (stay_started_at IS NOT NULL AND stay_started_by_user_id IS NOT NULL AND stay_started_at >= checked_in_at)", name="ck_stay_started"),
        CheckConstraint("(checked_out_at IS NULL AND checked_out_by_user_id IS NULL) OR (checked_out_at IS NOT NULL AND checked_out_by_user_id IS NOT NULL AND stay_started_at IS NOT NULL AND checked_out_at >= stay_started_at)", name="ck_stay_checkout"),
        CheckConstraint("(completed_at IS NULL AND completed_by_user_id IS NULL) OR (completed_at IS NOT NULL AND completed_by_user_id IS NOT NULL AND checked_out_at IS NOT NULL AND completed_at >= checked_out_at)", name="ck_stay_completion"),
    )


class BoardingNote(Base):
    __tablename__ = "boarding_notes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stay_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boarding_stays.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("booking_events.id", ondelete="RESTRICT"), nullable=False, unique=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("length(trim(note)) BETWEEN 1 AND 4000 AND note = trim(note)", name="ck_boarding_note"),
    )


class StaffAvailability(Base):
    __tablename__ = "staff_availability"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    staff_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    staff_role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), nullable=False, server_default="STAFF", default=Role.STAFF)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["staff_user_id", "staff_role"], ["users.id", "users.role"], ondelete="RESTRICT", name="fk_availability_staff_role"),
        CheckConstraint("staff_role = 'STAFF' AND ends_at > starts_at", name="ck_availability_window"),
    )


class Accommodation(Base):
    __tablename__ = "accommodations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reservation_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    updated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_accommodation_capacity"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 120 AND name = trim(name) AND length(trim(category)) BETWEEN 1 AND 120 AND category = trim(category)", name="ck_accommodation_name"),
    )


class BoardingAllocation(Base):
    __tablename__ = "boarding_allocations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False)
    accommodation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accommodations.id", ondelete="RESTRICT"), nullable=False, index=True)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    __table_args__ = (
        UniqueConstraint("booking_id", "id", name="uq_allocation_booking_id"),
        CheckConstraint("ends_on > starts_on", name="ck_allocation_dates"),
        CheckConstraint("(released_at IS NULL AND released_by_user_id IS NULL) OR (released_at IS NOT NULL AND released_by_user_id IS NOT NULL AND released_at >= created_at)", name="ck_allocation_release"),
        Index("uq_current_booking_allocation", "booking_id", unique=True, postgresql_where=text("released_at IS NULL"), sqlite_where=text("released_at IS NULL")),
    )


NOTIFICATION_KINDS = ("BOOKING_SUBMITTED", "BOOKING_CONFIRMED", "BOOKING_REJECTED",
    "BOOKING_RESCHEDULED", "BOOKING_RECONFIRMED", "RESCHEDULE_REJECTED", "BOOKING_CANCELLED",
    "STAFF_ASSIGNED", "STAFF_REASSIGNED", "BOOKING_REMINDER")


class NotificationSetting(Base):
    __tablename__ = "notification_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    lead_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_notification_setting_singleton"),
        CheckConstraint("(lead_minutes IS NULL OR lead_minutes BETWEEN 1 AND 525600) AND (NOT enabled OR lead_minutes IS NOT NULL)", name="ck_notification_lead"),
        CheckConstraint("(updated_by_user_id IS NULL AND updated_at IS NULL) OR (updated_by_user_id IS NOT NULL AND updated_at IS NOT NULL)", name="ck_notification_setting_actor"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    recipient_role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), nullable=False)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_event_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_reference: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["recipient_user_id", "recipient_role"], ["users.id", "users.role"], name="fk_notification_recipient_role", ondelete="RESTRICT"),
        ForeignKeyConstraint(["booking_id", "source_event_id"], ["booking_events.booking_id", "booking_events.id"], name="fk_notification_booking_event", ondelete="RESTRICT"),
        UniqueConstraint("recipient_user_id", "source_event_id", "kind", name="uq_notification_event_recipient_kind"),
        CheckConstraint("recipient_role IN ('CUSTOMER','STAFF')", name="ck_notification_recipient"),
        CheckConstraint("kind IN ("+','.join("'"+k+"'" for k in NOTIFICATION_KINDS)+")", name="ck_notification_kind"),
        CheckConstraint("read_at IS NULL OR read_at >= created_at", name="ck_notification_read_time"),
        CheckConstraint("(kind = 'BOOKING_REMINDER' AND schedule_reference IS NOT NULL AND lead_minutes IS NOT NULL AND lead_minutes BETWEEN 1 AND 525600) OR (kind <> 'BOOKING_REMINDER' AND schedule_reference IS NULL AND lead_minutes IS NULL)", name="ck_notification_reminder_shape"),
        Index("ix_notification_inbox", "recipient_user_id", "created_at", "id"),
    )


class ManagementEvent(Base):
    __tablename__ = "management_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    actor_role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), nullable=False, default=Role.ADMIN, server_default="ADMIN")
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"), nullable=True, index=True)
    notification_setting_id: Mapped[int | None] = mapped_column(ForeignKey("notification_settings.id", ondelete="RESTRICT"), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["actor_user_id", "actor_role"], ["users.id", "users.role"], name="fk_management_actor_role", ondelete="RESTRICT"),
        CheckConstraint("actor_role = 'ADMIN'", name="ck_management_actor"),
        CheckConstraint("(action IN ('STAFF_CREATED','STAFF_UPDATED') AND staff_user_id IS NOT NULL AND service_id IS NULL AND notification_setting_id IS NULL) OR (action IN ('SERVICE_CREATED','SERVICE_UPDATED') AND service_id IS NOT NULL AND staff_user_id IS NULL AND notification_setting_id IS NULL) OR (action = 'REMINDER_SETTINGS_UPDATED' AND notification_setting_id IS NOT NULL AND staff_user_id IS NULL AND service_id IS NULL)", name="ck_management_target"),
    )
