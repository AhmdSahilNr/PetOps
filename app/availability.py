"""Slice 2 resource rules. SQL constraints are the final concurrency safeguard."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select

from .models import Accommodation, BoardingAllocation, Booking, BookingStatus, Role, StaffResponsibility, User, utcnow

ACTIVE_WORK = {BookingStatus.SUBMITTED, BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS,
               BookingStatus.CHECKED_IN, BookingStatus.STAYING}
BUSINESS_ZONE = ZoneInfo("Asia/Kuala_Lumpur")


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def grooming_end(start, duration):
    if not duration or duration <= 0:
        raise HTTPException(409, "BR-002: configure Grooming duration before booking/confirmation")
    try:
        return aware(start) + timedelta(minutes=duration)
    except (OverflowError, ValueError):
        raise HTTPException(422, "Grooming period exceeds supported datetime range")


def eligible_staff(db, start, end, exclude_booking_id=None):
    start, end = aware(start), aware(end)
    result = []
    for user in db.scalars(select(User).where(User.role == Role.STAFF, User.is_active.is_(True)).order_by(User.id)):
        conflict=select(StaffResponsibility.id).where(StaffResponsibility.staff_user_id==user.id,
            StaffResponsibility.released_at.is_(None),StaffResponsibility.starts_at<end,
            func.coalesce(StaffResponsibility.ended_at,StaffResponsibility.ends_at)>start)
        unknown=select(Booking.id).where(Booking.assigned_staff_user_id==user.id,Booking.status.in_(ACTIVE_WORK),
            or_(Booking.staff_start.is_(None),Booking.staff_end.is_(None)))
        if exclude_booking_id:
            conflict=conflict.where(StaffResponsibility.booking_id!=exclude_booking_id)
            unknown=unknown.where(Booking.id!=exclude_booking_id)
        if db.scalar(unknown.limit(1)) is not None:continue
        if db.scalar(conflict.limit(1)) is None:
            result.append(user.id)
    return result


def require_grooming_available(db, start, duration, exclude_booking_id=None):
    end = grooming_end(start, duration)
    eligible = eligible_staff(db, start, end, exclude_booking_id)
    if not eligible:
        raise HTTPException(409, "No active available Staff without a conflicting assignment for the full Grooming duration")
    return eligible


def peak_occupancy(rows, start=None, end=None):
    """Group equal date edges before summing: end-exclusive stays can touch."""
    edges = {}
    for row in rows:
        lo = max(row.starts_on, start) if start else row.starts_on
        hi = min(row.ends_on, end) if end else row.ends_on
        if lo >= hi:
            continue
        edges[lo] = edges.get(lo, 0) + 1
        edges[hi] = edges.get(hi, 0) - 1
    used = peak = 0
    for day in sorted(edges):
        used += edges[day]
        peak = max(peak, used)
    return peak


def boarding_capacity(db, start, end, exclude_booking_id=None):
    result = []
    for unit in db.scalars(select(Accommodation).where(Accommodation.is_active.is_(True)).order_by(Accommodation.name)):
        query = select(BoardingAllocation).where(BoardingAllocation.accommodation_id == unit.id,
            BoardingAllocation.released_at.is_(None), BoardingAllocation.starts_on < end,
            BoardingAllocation.ends_on > start)
        if exclude_booking_id:
            query = query.where(BoardingAllocation.booking_id != exclude_booking_id)
        peak = peak_occupancy(db.scalars(query).all(), start, end)
        result.append({"accommodation_id": str(unit.id), "name": unit.name, "capacity": unit.capacity,
                       "peak_occupancy": peak, "available_places": max(0, unit.capacity - peak)})
    return result


def require_boarding_available(db, start, end, exclude_booking_id=None):
    options = boarding_capacity(db, start, end, exclude_booking_id)
    if not any(row["available_places"] > 0 for row in options):
        raise HTTPException(409, "No configured active accommodation has capacity throughout the requested stay")
    return options


def current_allocations(db, booking_id):
    return db.scalars(select(BoardingAllocation).where(BoardingAllocation.booking_id == booking_id,
        BoardingAllocation.released_at.is_(None))).all()


def release_resources(db, booking, actor):
    from .responsibilities import withdraw
    withdraw(db,booking,actor)
    old = {"staff_user_id": str(booking.assigned_staff_user_id) if booking.assigned_staff_user_id else None,
           "staff_start": aware(booking.staff_start).isoformat() if booking.staff_start else None,
           "staff_end": aware(booking.staff_end).isoformat() if booking.staff_end else None,
           "allocations": []}
    for allocation in current_allocations(db, booking.id):
        old["allocations"].append({"id": str(allocation.id), "accommodation_id": str(allocation.accommodation_id),
                                  "starts_on": allocation.starts_on.isoformat(), "ends_on": allocation.ends_on.isoformat()})
        allocation.released_at = utcnow()
        allocation.released_by_user_id = actor.id
    # Flush releases before adding any replacement reservation. Same transaction.
    db.flush()
    booking.assigned_staff_user_id = None
    booking.staff_start = booking.staff_end = None
    return old


def validate_staff_assignment(db, booking, staff_id, start=None, end=None):
    from .models import ServiceType
    if booking.booking_type == ServiceType.GROOMING:
        if start is not None or end is not None:
            raise HTTPException(422, "Grooming work period is derived from the booking duration")
        start = aware(booking.grooming_start)
        end = grooming_end(start, booking.grooming_duration_minutes)
    else:
        from .responsibilities import booking_period
        lo,hi=booking_period(booking)
        # Confirmation may recheck an imported legacy duty period; new API assignments derive it.
        if start is None and end is None:start,end=lo,hi
        elif start is None or end is None or not lo<=aware(start)<aware(end)<=hi:
            raise HTTPException(409,"Recorded responsibility must remain inside the stay")
    if staff_id not in eligible_staff(db, start, end, booking.id):
        raise HTTPException(409, "Staff must be active and free of conflicting PetOps assignments")
    return start, end
