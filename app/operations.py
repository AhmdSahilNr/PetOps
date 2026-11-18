"""Admin operations centre and lodging board: read-only views over existing records.

Every list below is defined once, on the server. The UI shows len(items) as the
count and the same items as the drill-down, so a count can never disagree with
its list. No rule, status, capacity or responsibility logic is changed here.
Business dates are MYT (services.business_today); instants are UTC.
"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .availability import ACTIVE_WORK, aware, current_allocations, peak_occupancy
from .database import get_db
from .management import period_bounds
from .models import (Accommodation, BoardingAllocation, BoardingStay, Booking, BookingEvent, BookingStatus,
                     Customer, Pet, Role, Service, ServiceType, StaffResponsibility, User, utcnow)
from .security import require_roles
from .services import business_today, utc_iso

router = APIRouter(prefix='/admin', tags=['Admin operations centre'])
admin = require_roles(Role.ADMIN)

DEFINITIONS = {
    # Plain-language definitions (shown to Admin; QA F-19). The rules themselves live in the queries below.
    'needs_decision': 'Requests waiting for a confirm or reject decision, oldest first. Grooming needs a groomer and Boarding needs '
                      'accommodation before it can be confirmed. "Date passed" means the appointment or check-in date has gone, so the '
                      'request can no longer be confirmed: reject it or change its dates.',
    'changed_requests': 'Requests whose dates were changed and now need a new decision.',
    'grooming_today': 'Confirmed, in-progress and completed grooming appointments starting today. Requests, rejected and cancelled bookings are not included.',
    'arrivals_today': 'Confirmed stays with check-in today.',
    'departures_due': 'Pets staying with planned check-out today or earlier. Earlier ones are past their planned check-out.',
    'in_care': 'Pets checked in and not yet checked out.',
    'coming_up': 'Confirmed grooming and confirmed check-ins from tomorrow through the next 7 days.',
    'staff_work': 'Bookings each active team member is responsible for now, or from within the next 7 days.',
    'capacity_now': 'Places in active accommodation, minus pets in care right now.',
}


OPEN_STAY = (BookingStatus.STAYING, BookingStatus.CHECKED_IN)


def is_overdue_stay(b, today):
    """Derived, display-only exception: the planned check-out date (MYT) has passed while the stay is still open.
    No fee, extension, automatic check-out or date change follows from it. Departure today is not overdue."""
    return (b.booking_type == ServiceType.BOARDING and b.status in OPEN_STAY
            and b.boarding_end is not None and b.boarding_end < today)


def row(db, b, flags=(), cache=None):
    cache = cache if cache is not None else {}
    def get(model, key):
        k = (model.__name__, key)
        if k not in cache:
            cache[k] = db.get(model, key) if key else None
        return cache[k]
    staff = get(User, b.assigned_staff_user_id)
    unit_name = None
    if b.booking_type == ServiceType.BOARDING:
        allocations = current_allocations(db, b.id)
        if allocations:
            unit = get(Accommodation, allocations[0].accommodation_id)
            unit_name = unit.name if unit else None
    return {'id': str(b.id), 'booking_type': b.booking_type.value, 'status': b.status.value,
            'pet_name': get(Pet, b.pet_id).name, 'customer_name': get(Customer, b.customer_id).display_name,
            'service_name': get(Service, b.service_id).name, 'created_at': utc_iso(b.created_at),
            'grooming_start': utc_iso(b.grooming_start), 'grooming_duration_minutes': b.grooming_duration_minutes,
            'boarding_start': b.boarding_start.isoformat() if b.boarding_start else None,
            'boarding_end': b.boarding_end.isoformat() if b.boarding_end else None,
            'assigned_staff_name': (staff.display_name or staff.email) if staff else None,
            'accommodation_name': unit_name, 'flags': list(flags)}


def capacity_now(db):
    units = []
    for unit in db.scalars(select(Accommodation).order_by(Accommodation.name)):
        occupied = db.scalar(select(func.count()).select_from(BoardingStay).join(
            BoardingAllocation, BoardingAllocation.id == BoardingStay.allocation_id).where(
            BoardingAllocation.accommodation_id == unit.id, BoardingStay.checked_out_at.is_(None)))
        units.append({'id': str(unit.id), 'name': unit.name, 'category': unit.category, 'is_active': unit.is_active,
                      'capacity': unit.capacity, 'occupied': occupied,
                      'available': max(0, unit.capacity - occupied) if unit.is_active else 0})
    capacity = sum(u['capacity'] for u in units if u['is_active'])
    occupied = sum(u['occupied'] for u in units)
    return {'capacity': capacity, 'occupied': occupied, 'available': sum(u['available'] for u in units), 'units': units}


@router.get('/operations')
def operations(user=Depends(admin), db: Session = Depends(get_db)):
    now, today = utcnow(), business_today()
    cache = {}
    # Needs decision (SUBMITTED), oldest first.
    needs, changed = [], []
    for b in db.scalars(select(Booking).where(Booking.status == BookingStatus.SUBMITTED).order_by(Booking.created_at, Booking.id)):
        if b.booking_type == ServiceType.GROOMING:
            readiness = 'date_passed' if aware(b.grooming_start) <= now else ('ready' if b.assigned_staff_user_id else 'needs_staff')
        else:
            readiness = 'date_passed' if b.boarding_start < today else ('ready' if current_allocations(db, b.id) else 'needs_accommodation')
        latest = db.scalar(select(BookingEvent.event_type).where(BookingEvent.booking_id == b.id)
                           .order_by(BookingEvent.created_at.desc(), BookingEvent.id.desc()).limit(1))
        flags = [readiness] + (['changed'] if latest == 'BOOKING_RESCHEDULED' else [])
        item = row(db, b, flags, cache)
        needs.append(item)
        if 'changed' in flags:
            changed.append(item)
    lo, hi = period_bounds(today, today)
    grooming_today = [row(db, b, ['start_passed'] if b.status == BookingStatus.CONFIRMED and aware(b.grooming_start) <= now else [], cache)
                      for b in db.scalars(select(Booking).where(
                          Booking.booking_type == ServiceType.GROOMING,
                          Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED]),
                          Booking.grooming_start >= lo, Booking.grooming_start < hi).order_by(Booking.grooming_start, Booking.id))]
    arrivals = [row(db, b, [], cache) for b in db.scalars(select(Booking).where(
        Booking.booking_type == ServiceType.BOARDING, Booking.status == BookingStatus.CONFIRMED,
        Booking.boarding_start == today).order_by(Booking.created_at, Booking.id))]
    departures = [row(db, b, ['past_planned_checkout'] if is_overdue_stay(b, today) else [], cache) for b in db.scalars(select(Booking).where(
        Booking.booking_type == ServiceType.BOARDING, Booking.status.in_([BookingStatus.STAYING, BookingStatus.CHECKED_IN]),
        Booking.boarding_end <= today).order_by(Booking.boarding_end, Booking.id))]
    in_care = [row(db, b, ['past_planned_checkout'] if is_overdue_stay(b, today) else [], cache) for b in db.scalars(
        select(Booking).join(BoardingStay, BoardingStay.booking_id == Booking.id).where(
            BoardingStay.checked_out_at.is_(None)).order_by(Booking.boarding_end, Booking.id))]
    first, last = today + timedelta(days=1), today + timedelta(days=7)
    c_lo, c_hi = period_bounds(first, last)
    coming = [row(db, b, [], cache) for b in db.scalars(select(Booking).where(
        Booking.booking_type == ServiceType.GROOMING, Booking.status == BookingStatus.CONFIRMED,
        Booking.grooming_start >= c_lo, Booking.grooming_start < c_hi))]
    coming += [row(db, b, [], cache) for b in db.scalars(select(Booking).where(
        Booking.booking_type == ServiceType.BOARDING, Booking.status == BookingStatus.CONFIRMED,
        Booking.boarding_start >= first, Booking.boarding_start <= last))]
    def when(r):
        from datetime import datetime, time
        from zoneinfo import ZoneInfo
        if r['grooming_start']:
            return datetime.fromisoformat(r['grooming_start'])
        return datetime.combine(date.fromisoformat(r['boarding_start']), time.min, ZoneInfo('Asia/Kuala_Lumpur'))
    coming.sort(key=lambda r: (when(r), r['id']))
    horizon = now + timedelta(days=7)
    staff_work = []
    for staff in db.scalars(select(User).where(User.role == Role.STAFF, User.is_active.is_(True)).order_by(User.display_name, User.email)):
        live = db.execute(select(StaffResponsibility, Booking).join(Booking, Booking.id == StaffResponsibility.booking_id).where(
            StaffResponsibility.staff_user_id == staff.id, StaffResponsibility.released_at.is_(None),
            Booking.status.in_(ACTIVE_WORK),
            func.coalesce(StaffResponsibility.ended_at, StaffResponsibility.ends_at) > now,
            StaffResponsibility.starts_at <= horizon).order_by(StaffResponsibility.starts_at)).all()
        current, upcoming, seen = [], [], set()
        for resp, b in live:
            if b.id in seen:
                continue
            seen.add(b.id)
            item = {**row(db, b, [], cache), 'responsibility_starts_at': utc_iso(resp.starts_at),
                    'responsibility_ends_at': utc_iso(resp.ended_at or resp.ends_at)}
            (current if aware(resp.starts_at) <= now else upcoming).append(item)
        staff_work.append({'staff_user_id': str(staff.id), 'name': staff.display_name or staff.email,
                           'now': current, 'next_7_days': upcoming})
    return {'as_of': utc_iso(now), 'business_date': today.isoformat(), 'timezone': 'Asia/Kuala_Lumpur',
            'needs_decision': needs, 'changed_requests': changed, 'grooming_today': grooming_today,
            'arrivals_today': arrivals, 'departures_due': departures, 'in_care': in_care, 'coming_up': coming,
            'coming_up_range': {'from_date': first.isoformat(), 'to_date': last.isoformat()},
            'staff_work': staff_work, 'capacity_now': capacity_now(db), 'definitions': DEFINITIONS}


@router.get('/boarding/board')
def lodging_board(user=Depends(admin), db: Session = Depends(get_db), start: date | None = None,
                  nights: int = Query(14, ge=1, le=31)):
    """Accommodation x night reservation grid from unreleased allocations (the inputs of peak_occupancy)."""
    today = business_today()
    first = max(start or today, today)  # past nights cannot be reconstructed: allocations are released at check-out
    end = first + timedelta(days=nights)
    days = [first + timedelta(days=i) for i in range(nights)]
    cache = {}
    open_stays = {s.booking_id: s for s in db.scalars(select(BoardingStay).where(BoardingStay.checked_out_at.is_(None)))}
    units = []
    for unit in db.scalars(select(Accommodation).order_by(Accommodation.name)):
        allocations = db.scalars(select(BoardingAllocation).where(
            BoardingAllocation.accommodation_id == unit.id, BoardingAllocation.released_at.is_(None),
            BoardingAllocation.starts_on < end, BoardingAllocation.ends_on > first)
            .order_by(BoardingAllocation.starts_on, BoardingAllocation.id)).all()
        if not unit.is_active and not allocations:
            continue
        stays = []
        for a in allocations:
            b = db.get(Booking, a.booking_id)
            stays.append({**row(db, b, (['in_care'] if b.id in open_stays else []) + (['past_planned_checkout'] if is_overdue_stay(b, today) else []), cache),
                          'starts_on': a.starts_on.isoformat(), 'ends_on': a.ends_on.isoformat()})
        per_night = [{'date': d.isoformat(), 'reserved': sum(1 for a in allocations if a.starts_on <= d < a.ends_on),
                      'capacity': unit.capacity if unit.is_active else 0} for d in days]
        occupied = sum(1 for a in allocations if a.booking_id in open_stays)
        units.append({'id': str(unit.id), 'name': unit.name, 'category': unit.category, 'capacity': unit.capacity,
                      'is_active': unit.is_active, 'notes': unit.notes, 'occupied_now': occupied,
                      'peak_reserved': peak_occupancy(allocations, first, end), 'nights': per_night, 'stays': stays})
    totals = [{'date': d.isoformat(), 'reserved': sum(u['nights'][i]['reserved'] for u in units),
               'capacity': sum(u['nights'][i]['capacity'] for u in units)} for i, d in enumerate(days)]
    return {'start': first.isoformat(), 'nights': nights, 'end_exclusive': end.isoformat(), 'today': today.isoformat(),
            'units': units, 'totals': totals,
            'definition': 'Reserved places per night = unreleased accommodation allocations covering that night '
                          '(check-out date excluded), the same inputs used for capacity checks. Includes requested '
                          'bookings already holding an allocation. Past nights are not shown because allocations are '
                          'released at check-out.'}
