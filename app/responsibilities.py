"""Approved booking-derived responsibility periods; no generic shift calendar."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select
from .models import Booking, BookingStatus, Customer, Pet, Role, Service, ServiceType, StaffResponsibility, User, utcnow

LIVE = {BookingStatus.SUBMITTED, BookingStatus.CONFIRMED, BookingStatus.IN_PROGRESS, BookingStatus.CHECKED_IN, BookingStatus.STAYING}

def instant(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

def booking_period(b):
    if b.booking_type == ServiceType.GROOMING:
        from .availability import grooming_end
        return instant(b.grooming_start), grooming_end(b.grooming_start,b.grooming_duration_minutes)
    zone=ZoneInfo('Asia/Kuala_Lumpur')
    return tuple(datetime.combine(d,time.min,zone).astimezone(timezone.utc) for d in (b.boarding_start,b.boarding_end))

def period_end(row):
    return instant(row.ended_at or row.ends_at)

def rows_for(db,bid):
    return db.scalars(select(StaffResponsibility).where(StaffResponsibility.booking_id==bid).order_by(StaffResponsibility.starts_at,StaffResponsibility.created_at,StaffResponsibility.id)).all()

def current_staff(db,b,at=None):
    now=at or utcnow()
    rows=[r for r in rows_for(db,b.id) if r.released_at is None and instant(r.starts_at)<=now]
    if not rows:
        legacy=[r for r in rows_for(db,b.id) if r.released_at is None and r.created_by_user_id is None and r.ended_at is None]
        return legacy[-1].staff_user_id if legacy and b.status in LIVE else None
    row=max(rows,key=lambda r:instant(r.starts_at))
    if period_end(row)>now:return row.staff_user_id
    # An overdue open stay remains someone's responsibility until checkout.
    if b.booking_type==ServiceType.BOARDING and b.status in LIVE and row.ended_at is None:return row.staff_user_id
    return None

def staff_scope(user_id):
    now=utcnow()
    assigned=exists(select(StaffResponsibility.id).where(StaffResponsibility.booking_id==Booking.id,
        StaffResponsibility.staff_user_id==user_id,StaffResponsibility.released_at.is_(None),
        func.coalesce(StaffResponsibility.ended_at,StaffResponsibility.ends_at)>now))
    # The last responsible person keeps unresolved/overdue work and history.
    # A planned clock period is not an authorization timeout. A future handover
    # additionally retains the current person's access until its effective end.
    return or_(assigned,Booking.assigned_staff_user_id==user_id)

def can_inspect(db,b,user_id):
    return db.scalar(select(Booking.id).where(Booking.id==b.id,staff_scope(user_id))) is not None

def view(db,row):
    from .services import utc_iso
    staff=db.get(User,row.staff_user_id)
    creator=db.get(User,row.created_by_user_id) if row.created_by_user_id else None
    ending=db.get(User,row.ended_by_user_id) if row.ended_by_user_id else None
    return {'id':str(row.id),'staff_user_id':str(row.staff_user_id),'staff_name':staff.display_name or 'Name not recorded',
        'starts_at':utc_iso(row.starts_at),'ends_at':utc_iso(row.ends_at),'effective_end':utc_iso(row.ended_at or row.ends_at),
        'released_at':utc_iso(row.released_at),'recorded_at':utc_iso(row.created_at),'ended_at':utc_iso(row.ended_at),
        'recorded_by':(creator.display_name or 'Admin') if creator else 'Original actor not recorded',
        'ended_by':(ending.display_name or 'Admin') if ending else None}

def withdraw(db,b,actor):
    for row in rows_for(db,b.id):
        if row.released_at is None:row.released_at=utcnow()
    db.flush()

def assign(db,b,staff_id,actor,effective_at=None):
    from .availability import eligible_staff
    from .services import add_event, utc_iso
    active=b.status in {BookingStatus.STAYING,BookingStatus.CHECKED_IN}
    if b.status not in {BookingStatus.SUBMITTED,BookingStatus.CONFIRMED} and not (b.booking_type==ServiceType.BOARDING and active):
        raise HTTPException(409,'Staff can be changed only before fulfilment or during an active Boarding stay')
    start,end=booking_period(b);old=b.assigned_staff_user_id
    old_work={'starts_at':utc_iso(b.staff_start),'ends_at':utc_iso(b.staff_end)}
    rows=rows_for(db,b.id);live=[r for r in rows if r.released_at is None]
    if active:
        if staff_id is None:raise HTTPException(409,'Choose the next responsible Staff member for an active stay')
        start=effective_at or utcnow()
        start=instant(start)
        if start<utcnow().replace(microsecond=0) or not booking_period(b)[0]<=start<end:
            raise HTTPException(422,'Effective time must be now or later and inside the stay')
        if live and any(r.created_by_user_id is not None and start<instant(r.starts_at) for r in live):
            raise HTTPException(409,'Use the scheduled responsibility change time or a later time')
    elif effective_at is not None:raise HTTPException(422,'Initial assignment inherits the booking dates')
    if staff_id is None and b.booking_type==ServiceType.GROOMING and b.status==BookingStatus.CONFIRMED:
        raise HTTPException(409,'Confirmed Grooming requires Staff; reassign instead')
    if staff_id is not None:
        staff=db.scalar(select(User).where(User.id==staff_id).with_for_update())
        if not staff or staff.role!=Role.STAFF or not staff.is_active:raise HTTPException(409,'Choose active Staff')
        if staff_id not in eligible_staff(db,start,end,b.id):raise HTTPException(409,'This Staff member has conflicting PetOps work')
    if active:
        for row in live:
            if instant(row.starts_at)>=start:row.released_at=utcnow()
            elif period_end(row)>start:row.ended_at,row.ended_by_user_id=start,actor.id
    else:
        for row in live:row.released_at=utcnow()
    db.flush()
    b.assigned_staff_user_id=staff_id;b.staff_start=start if staff_id else None;b.staff_end=end if staff_id else None
    db.flush()
    row=None
    if staff_id:
        row=StaffResponsibility(booking_id=b.id,staff_user_id=staff_id,starts_at=start,ends_at=end,created_by_user_id=actor.id)
        db.add(row);db.flush()
    add_event(db,b,actor,'STAFF_ASSIGNED' if staff_id else 'STAFF_UNASSIGNED',old_status=b.status,new_status=b.status,
        old_assigned_staff_user_id=old,details={'old_work':old_work,'new_work':{'starts_at':utc_iso(b.staff_start),'ends_at':utc_iso(b.staff_end)},
        'responsibility_id':str(row.id) if row else None,'effective_at':utc_iso(start) if staff_id else None})
    return {'booking_id':str(b.id),'staff_user_id':str(staff_id) if staff_id else None,'starts_at':utc_iso(b.staff_start),'ends_at':utc_iso(b.staff_end)}
