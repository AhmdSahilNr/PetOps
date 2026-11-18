"""Bounded Grooming work, completion and retained history (Slice 3)."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .availability import eligible_staff, grooming_end
from .database import get_db
from .models import (Booking, BookingEvent, BookingStatus, Customer, GroomingRecord,
                     Pet, Role, Service, ServiceType, StaffResponsibility, User, utcnow)
from .schemas import GroomingCompleteIn, InputModel
from .security import get_current_user, require_roles
from .services import add_event, customer_for_user, utc_iso
from .views import booking_view, event_view

router = APIRouter(prefix="/grooming", tags=["Grooming"])
operators = require_roles(Role.STAFF, Role.ADMIN)


def scoped_query(db, user):
    query = select(Booking).where(Booking.booking_type == ServiceType.GROOMING)
    if user.role == Role.CUSTOMER:
        query = query.where(Booking.customer_id == customer_for_user(db, user).id)
    elif user.role == Role.STAFF:
        from .responsibilities import staff_scope
        query=query.where(staff_scope(user.id))
    elif user.role != Role.ADMIN:
        raise HTTPException(403, "Action not permitted for this role")
    return query


def find_work(db, user, booking_id, lock=False):
    query = scoped_query(db, user).where(Booking.id == booking_id)
    b = db.scalar(query.with_for_update() if lock else query)
    if not b:
        raise HTTPException(404, "Permitted Grooming booking not found")
    return b


def record_view(r):
    if r is None:
        return None
    return {"id": str(r.id), "booking_id": str(r.booking_id),
        "started_by_user_id": str(r.started_by_user_id), "started_at": utc_iso(r.started_at),
        "completed_by_user_id": str(r.completed_by_user_id) if r.completed_by_user_id else None,
        "completed_at": utc_iso(r.completed_at), "service_notes": r.service_notes}


def detail(db, b, audience=None):
    customer, pet, service = db.get(Customer, b.customer_id), db.get(Pet, b.pet_id), db.get(Service, b.service_id)
    record = db.scalar(select(GroomingRecord).where(GroomingRecord.booking_id == b.id))
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == b.id)
        .order_by(BookingEvent.created_at, BookingEvent.id)).all()
    from .responsibilities import rows_for,view
    out = {"responsibilities":[view(db,row) for row in rows_for(db,b.id)],"booking": booking_view(b), "customer_name": customer.display_name,
        "pet_name": pet.name, "service_name": service.name, "grooming_record": record_view(record),
        "history": [event_view(e) for e in events]}
    if audience:
        from .timeline import build
        out["timeline"] = build(db, b, audience)
    return out


def audience_for(user):
    return {Role.CUSTOMER: 'customer', Role.STAFF: 'staff', Role.ADMIN: 'admin'}[user.role]


@router.get("/bookings")
def work_list(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(scoped_query(db, user).order_by(Booking.created_at.desc())).all()
    # Deliberately a bounded Grooming worklist, not operational analytics.
    out = [{**booking_view(b), "pet_name": db.get(Pet, b.pet_id).name,
             "service_name": db.get(Service, b.service_id).name,"customer_name":db.get(Customer,b.customer_id).display_name} for b in rows]
    if user.role == Role.CUSTOMER:
        from .projections import customer_booking
        out = [customer_booking(row) for row in out]
    return out


@router.get("/bookings/{booking_id}")
def work_detail(booking_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = detail(db, find_work(db, user, booking_id), audience_for(user))
    if user.role == Role.CUSTOMER:
        from .projections import customer_detail
        out = customer_detail(out)
    return out


@router.get("/bookings/{booking_id}/eligible-staff")
def work_candidates(booking_id: UUID, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    b = find_work(db, user, booking_id)
    if b.status not in {BookingStatus.SUBMITTED, BookingStatus.CONFIRMED}:
        raise HTTPException(409, "Assignment is closed once work begins")
    end = grooming_end(b.grooming_start, b.grooming_duration_minutes)
    ids = eligible_staff(db, b.grooming_start, end, b.id)
    return [{"id": str(u.id), "email": u.email,"display_name":u.display_name} for u in
        db.scalars(select(User).where(User.id.in_(ids)).order_by(User.email))]


def holds_open_responsibility(db, b, user):
    # Clock-free ownership: Staff may act only while this booking has an unreleased
    # responsibility row for them. Reassignment releases the old row. No planned
    # time window is applied here, so no time cutoff is introduced.
    return db.scalar(select(StaffResponsibility.id).where(StaffResponsibility.booking_id == b.id,
        StaffResponsibility.staff_user_id == user.id, StaffResponsibility.released_at.is_(None))) is not None


@router.post("/bookings/{booking_id}/start")
def start_work(booking_id: UUID, payload: InputModel, user: User = Depends(operators), db: Session = Depends(get_db)):
    b = find_work(db, user, booking_id, lock=True)
    if b.status != BookingStatus.CONFIRMED:
        raise HTTPException(409, "Only CONFIRMED Grooming may enter IN_PROGRESS")
    if user.role == Role.STAFF and not holds_open_responsibility(db, b, user):
        raise HTTPException(403, "Only currently responsible Staff can record Grooming actions")
    if not b.assigned_staff_user_id or not b.staff_start or not b.staff_end:
        raise HTTPException(409, "Confirmed eligible Staff assignment required")
    now = utcnow()
    b.status = BookingStatus.IN_PROGRESS
    db.flush()
    r = GroomingRecord(booking_id=b.id, started_by_user_id=user.id, started_at=now)
    db.add(r)
    db.flush()
    add_event(db, b, user, "GROOMING_STARTED", old_status=BookingStatus.CONFIRMED,
        new_status=b.status, old_assigned_staff_user_id=b.assigned_staff_user_id,
        created_at=now, details={"grooming_record_id": str(r.id)})
    db.commit()
    return detail(db, b)


@router.post("/bookings/{booking_id}/complete")
def complete_work(booking_id: UUID, payload: GroomingCompleteIn, user: User = Depends(operators), db: Session = Depends(get_db)):
    b = find_work(db, user, booking_id, lock=True)
    if b.status != BookingStatus.IN_PROGRESS:
        raise HTTPException(409, "Only IN_PROGRESS Grooming may become COMPLETED")
    if user.role == Role.STAFF and not holds_open_responsibility(db, b, user):
        raise HTTPException(403, "Only currently responsible Staff can record Grooming actions")
    r = db.scalar(select(GroomingRecord).where(GroomingRecord.booking_id == b.id))
    if r is None or r.completed_at is not None:
        raise HTTPException(409, "A single unfinished Grooming record is required")
    now = utcnow()
    b.status = BookingStatus.COMPLETED
    db.flush()
    r.completed_by_user_id, r.completed_at, r.service_notes = user.id, now, payload.service_notes
    add_event(db, b, user, "GROOMING_COMPLETED", old_status=BookingStatus.IN_PROGRESS,
        new_status=b.status, old_assigned_staff_user_id=b.assigned_staff_user_id,
        created_at=now, details={"grooming_record_id": str(r.id)})
    db.commit()
    return detail(db, b)
