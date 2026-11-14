from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import HTTPException

from .models import Accommodation, BoardingAllocation, Booking, BookingEvent, BookingStatus, Customer, Pet, Role, Service, ServiceType, User
from .availability import (aware, current_allocations, grooming_end, release_resources,
    require_boarding_available, require_grooming_available, validate_staff_assignment)

CUSTOMER_CHANGEABLE = {BookingStatus.SUBMITTED, BookingStatus.CONFIRMED}
ADMIN_DECISION_TRANSITIONS = {
    BookingStatus.SUBMITTED: {BookingStatus.CONFIRMED, BookingStatus.REJECTED},
}

BUSINESS_TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")


def business_today():
    return datetime.now(BUSINESS_TIMEZONE).date()


def utc_iso(value: datetime | None):
    if value is None:
        return None
    # SQLite drops timezone metadata; all accepted instants are normalized UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def schedule_snapshot(b: Booking) -> dict:
    return {
        "grooming_start": utc_iso(b.grooming_start),
        "grooming_duration_minutes": b.grooming_duration_minutes,
        "boarding_start": b.boarding_start.isoformat() if b.boarding_start else None,
        "boarding_end": b.boarding_end.isoformat() if b.boarding_end else None,
    }


def add_event(db: Session, booking: Booking, actor: User, event_type: str, *, old_status=None, new_status=None, old_schedule=None, new_schedule=None, old_assigned_staff_user_id=None, details=None, created_at=None):
    details=dict(details or {})
    details['notice_context']={'pet_name':db.get(Pet,booking.pet_id).name,'service_name':db.get(Service,booking.service_id).name,
        'schedule':schedule_snapshot(booking)}
    db.add(BookingEvent(
        booking_id=booking.id,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        old_schedule=old_schedule,
        new_schedule=new_schedule,
        actor_user_id=actor.id,
        old_assigned_staff_user_id=old_assigned_staff_user_id,
        new_assigned_staff_user_id=booking.assigned_staff_user_id,
        details=details,
        **({"created_at": created_at} if created_at else {}),
    ))


def customer_for_user(db: Session, user: User) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.user_id == user.id))
    if not customer:
        raise HTTPException(status_code=404, detail="Customer profile not found")
    return customer


def create_booking(db: Session, customer: Customer, actor: User, pet_id, service_id, grooming_start=None, boarding_start=None, boarding_end=None) -> Booking:
    pet = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.customer_id == customer.id))
    if not pet or not pet.is_active:
        raise HTTPException(status_code=404, detail="Pet not found for authenticated Customer")
    service = db.get(Service, service_id)
    if not service or not service.is_active:
        raise HTTPException(status_code=422, detail="Selected service is not active")

    if service.service_type == ServiceType.GROOMING:
        if grooming_start is None or boarding_start is not None or boarding_end is not None:
            raise HTTPException(status_code=422, detail="Grooming booking requires grooming_start only")
        if grooming_start.tzinfo is None or grooming_start.utcoffset() is None:
            raise HTTPException(status_code=422, detail="Grooming start must include a timezone offset")
        grooming_start = grooming_start.astimezone(timezone.utc)
        if grooming_start <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Grooming start must be in the future")
        booking_type = ServiceType.GROOMING
        require_grooming_available(db, grooming_start, service.duration_minutes)
    else:
        if grooming_start is not None or boarding_start is None or boarding_end is None or boarding_end <= boarding_start:
            raise HTTPException(status_code=422, detail="Boarding booking requires a valid future stay date range")
        if boarding_start < business_today():
            raise HTTPException(status_code=422, detail="Boarding start cannot be in the past")
        booking_type = ServiceType.BOARDING
        require_boarding_available(db, boarding_start, boarding_end)

    booking = Booking(
        customer_id=customer.id,
        pet_id=pet.id,
        service_id=service.id,
        booking_type=booking_type,
        status=BookingStatus.SUBMITTED,
        grooming_start=grooming_start,
        grooming_duration_minutes=service.duration_minutes if booking_type == ServiceType.GROOMING else None,
        boarding_start=boarding_start,
        boarding_end=boarding_end,
        created_by_user_id=actor.id,
    )
    db.add(booking)
    db.flush()
    add_event(db, booking, actor, "BOOKING_SUBMITTED", new_status=BookingStatus.SUBMITTED, new_schedule=schedule_snapshot(booking))
    db.commit()
    db.refresh(booking)
    return booking


def reschedule_booking(db: Session, booking: Booking, actor: User, *, grooming_start=None, boarding_start=None, boarding_end=None):
    if booking.status not in CUSTOMER_CHANGEABLE:
        raise HTTPException(status_code=409, detail="Booking is not Customer-changeable in its current status")
    old_status = booking.status
    old_schedule = schedule_snapshot(booking)
    old_staff = booking.assigned_staff_user_id
    service = db.get(Service, booking.service_id)
    if not service or not service.is_active:
        raise HTTPException(status_code=422, detail="Selected service is not active")

    if booking.booking_type == ServiceType.GROOMING:
        if grooming_start is None or boarding_start is not None or boarding_end is not None:
            raise HTTPException(status_code=422, detail="Grooming reschedule requires grooming_start only")
        if grooming_start.tzinfo is None or grooming_start.utcoffset() is None:
            raise HTTPException(status_code=422, detail="Grooming start must include a timezone offset")
        grooming_start = grooming_start.astimezone(timezone.utc)
        if grooming_start <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Grooming start must be in the future")
        require_grooming_available(db, grooming_start, service.duration_minutes, booking.id)
        old_resources = release_resources(db, booking, actor)
        booking.grooming_start = grooming_start
        booking.grooming_duration_minutes = service.duration_minutes
    else:
        if grooming_start is not None or boarding_start is None or boarding_end is None or boarding_end <= boarding_start:
            raise HTTPException(status_code=422, detail="Boarding reschedule requires a valid stay range")
        if boarding_start < business_today():
            raise HTTPException(status_code=422, detail="Boarding start cannot be in the past")
        require_boarding_available(db, boarding_start, boarding_end, booking.id)
        old_resources = release_resources(db, booking, actor)
        booking.boarding_start = boarding_start
        booking.boarding_end = boarding_end

    booking.status = BookingStatus.SUBMITTED
    booking.assigned_staff_user_id = None
    add_event(db, booking, actor, "BOOKING_RESCHEDULED", old_status=old_status, new_status=BookingStatus.SUBMITTED, old_schedule=old_schedule, new_schedule=schedule_snapshot(booking), old_assigned_staff_user_id=old_staff, details={"released_resources": old_resources})
    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(db: Session, booking: Booking, actor: User):
    if booking.status not in CUSTOMER_CHANGEABLE:
        raise HTTPException(status_code=409, detail="Booking is not Customer-changeable in its current status")
    old = booking.status
    old_staff = booking.assigned_staff_user_id
    resources = release_resources(db, booking, actor)
    booking.status = BookingStatus.CANCELLED
    add_event(db, booking, actor, "BOOKING_CANCELLED", old_status=old, new_status=BookingStatus.CANCELLED, old_assigned_staff_user_id=old_staff, details={"released_resources": resources})
    db.commit()
    db.refresh(booking)
    return booking


def admin_change_status(db: Session, booking: Booking, actor: User, target: BookingStatus):
    allowed = ADMIN_DECISION_TRANSITIONS.get(booking.status, set())
    if target not in allowed:
        raise HTTPException(status_code=409, detail=f"Invalid status transition: {booking.status.value} -> {target.value}")
    if target == BookingStatus.CONFIRMED:
        service = db.get(Service, booking.service_id)
        if not service or not service.is_active:
            raise HTTPException(409, "BR-002: active service required")
        if booking.booking_type == ServiceType.GROOMING:
            if aware(booking.grooming_start) <= datetime.now(timezone.utc) or not booking.assigned_staff_user_id:
                raise HTTPException(409, "BR-002: eligible Staff assignment and future schedule required")
            start, end = validate_staff_assignment(db, booking, booking.assigned_staff_user_id)
            if not booking.staff_start or aware(booking.staff_start) != start or not booking.staff_end or aware(booking.staff_end) != end:
                raise HTTPException(409, "BR-002: Grooming Staff window is stale")
        else:
            allocations = current_allocations(db, booking.id)
            if booking.boarding_start < business_today() or len(allocations) != 1:
                raise HTTPException(409, "BR-002: matching active accommodation allocation required")
            a = allocations[0]
            unit = db.get(Accommodation, a.accommodation_id)
            if not unit or not unit.is_active or a.starts_on != booking.boarding_start or a.ends_on != booking.boarding_end:
                raise HTTPException(409, "BR-002: accommodation allocation is stale or inactive")
            require_boarding_available(db, booking.boarding_start, booking.boarding_end, booking.id)
            if booking.assigned_staff_user_id:
                validate_staff_assignment(db, booking, booking.assigned_staff_user_id, booking.staff_start, booking.staff_end)
    old = booking.status
    old_staff = booking.assigned_staff_user_id
    details = None
    if target == BookingStatus.REJECTED:
        details = {"released_resources": release_resources(db, booking, actor)}
    booking.status = target
    add_event(db, booking, actor, "STATUS_CHANGED", old_status=old, new_status=target, old_assigned_staff_user_id=old_staff, details=details)
    db.commit()
    db.refresh(booking)
    return booking
