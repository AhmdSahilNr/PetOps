"""Small role-specific APIs needed by Slice 2; no fulfilment/UI expansion."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .availability import (ACTIVE_WORK, aware, boarding_capacity, current_allocations, eligible_staff,
    grooming_end, peak_occupancy)
from .database import get_db
from .models import (Accommodation, BoardingAllocation, Booking, BookingStatus, Role, Service,
                     ServiceType, StaffAvailability, User, utcnow)
from .schemas import (AccommodationIn, AllocationIn, AvailabilityQueryIn, DurationIn,
                      StaffAssignmentIn, StaffWindowIn)
from .security import get_current_user, require_roles
from .services import add_event, business_today, utc_iso

router = APIRouter()
admin_role = require_roles(Role.ADMIN)


def locked_booking(db, booking_id):
    row = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not row:
        raise HTTPException(404, "Booking not found")
    if row.status not in {BookingStatus.SUBMITTED, BookingStatus.CONFIRMED}:
        raise HTTPException(409, "Resources can be changed only for SUBMITTED or CONFIRMED bookings")
    return row


def allocation_view(row):
    return {"id": str(row.id), "accommodation_id": str(row.accommodation_id),
            "starts_on": row.starts_on.isoformat(), "ends_on": row.ends_on.isoformat(),
            "created_by_user_id": str(row.created_by_user_id), "created_at": utc_iso(row.created_at),
            "released_at": utc_iso(row.released_at)}


def accommodation_view(row):
    return {"id": str(row.id), "name": row.name, "category": row.category, "capacity": row.capacity,
            "is_active": row.is_active, "notes": row.notes,
            "updated_by_user_id": str(row.updated_by_user_id), "updated_at": utc_iso(row.updated_at)}


def window_view(row):
    return {"id": str(row.id), "staff_user_id": str(row.staff_user_id), "starts_at": utc_iso(row.starts_at),
            "ends_at": utc_iso(row.ends_at), "is_active": row.is_active,
            "updated_by_user_id": str(row.updated_by_user_id), "updated_at": utc_iso(row.updated_at)}


@router.put("/admin/services/{service_id}/duration")
def configure_duration(service_id: UUID, payload: DurationIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    row = db.scalar(select(Service).where(Service.id == service_id).with_for_update())
    if not row:
        raise HTTPException(404, "Service not found")
    if row.service_type != ServiceType.GROOMING:
        raise HTTPException(422, "Duration is a Grooming service attribute")
    row.duration_minutes = payload.duration_minutes
    row.updated_by_user_id = user.id
    row.updated_at = utcnow()
    db.commit()
    return {"id": str(row.id), "duration_minutes": row.duration_minutes,
            "updated_by_user_id": str(user.id), "updated_at": utc_iso(row.updated_at)}


@router.post("/admin/staff/{staff_id}/availability", status_code=201)
def create_window(staff_id: UUID, payload: StaffWindowIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    raise HTTPException(410,"Generic Staff availability has been retired; assignments use booking dates")


@router.put("/admin/staff/{staff_id}/availability/{window_id}")
def update_window(staff_id: UUID, window_id: UUID, payload: StaffWindowIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    raise HTTPException(410,"Generic Staff availability has been retired; assignments use booking dates")


@router.get("/admin/staff/{staff_id}/availability")
def admin_windows(staff_id: UUID, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    return [window_view(r) for r in db.scalars(select(StaffAvailability).where(StaffAvailability.staff_user_id == staff_id).order_by(StaffAvailability.starts_at))]


@router.get("/staff/availability")
def own_windows(user: User = Depends(require_roles(Role.STAFF)), db: Session = Depends(get_db)):
    raise HTTPException(410,"Generic Staff availability has been retired; assignments use booking dates")


@router.post("/admin/accommodations", status_code=201)
def create_accommodation(payload: AccommodationIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    row = Accommodation(**payload.model_dump(), updated_by_user_id=user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return accommodation_view(row)


@router.put("/admin/accommodations/{unit_id}")
def update_accommodation(unit_id: UUID, payload: AccommodationIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    row = db.scalar(select(Accommodation).where(Accommodation.id == unit_id).with_for_update())
    if not row:
        raise HTTPException(404, "Accommodation not found")
    allocations = db.scalars(select(BoardingAllocation).where(BoardingAllocation.accommodation_id == unit_id, BoardingAllocation.released_at.is_(None))).all()
    if peak_occupancy(allocations) > payload.capacity or (not payload.is_active and allocations):
        raise HTTPException(409, "Configuration would invalidate active allocations; release/reallocate them first")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_by_user_id, row.updated_at = user.id, utcnow()
    db.commit()
    return accommodation_view(row)


@router.get("/admin/accommodations")
def list_accommodations(user: User = Depends(admin_role), db: Session = Depends(get_db)):
    return [accommodation_view(r) for r in db.scalars(select(Accommodation).order_by(Accommodation.name))]


@router.post("/availability")
def check_availability(payload: AvailabilityQueryIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service = db.get(Service, payload.service_id)
    if not service or not service.is_active:
        raise HTTPException(422, "Selected service is not active")
    if service.service_type == ServiceType.GROOMING:
        if payload.grooming_start is None or payload.boarding_start is not None:
            raise HTTPException(422, "Grooming requires grooming_start only")
        if payload.grooming_start <= datetime.now(timezone.utc):
            raise HTTPException(422, "Grooming start must be in the future")
        end = grooming_end(payload.grooming_start, service.duration_minutes)
        return {"available": bool(eligible_staff(db, payload.grooming_start, end)),
                "duration_minutes": service.duration_minutes, "ends_at": utc_iso(end)}
    if payload.boarding_start is None or payload.grooming_start is not None or payload.boarding_start < business_today():
        raise HTTPException(422, "Boarding requires a valid non-past stay range")
    options = boarding_capacity(db, payload.boarding_start, payload.boarding_end)
    # Customers are not offered unit preference/allocation controls.
    return {"available": any(r["available_places"] > 0 for r in options)}


@router.post("/admin/boarding-availability")
def admin_boarding_capacity(payload: AvailabilityQueryIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    service = db.get(Service, payload.service_id)
    if not service or not service.is_active or service.service_type != ServiceType.BOARDING or payload.boarding_start is None:
        raise HTTPException(422, "Select an active Boarding service and valid stay range")
    if payload.boarding_start < business_today():
        raise HTTPException(422, "Boarding start cannot be in the past")
    return boarding_capacity(db, payload.boarding_start, payload.boarding_end)


@router.put("/admin/bookings/{booking_id}/staff")
def assign_staff(booking_id: UUID, payload: StaffAssignmentIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    from .responsibilities import assign
    b=db.scalar(select(Booking).where(Booking.id==booking_id).with_for_update())
    if not b:raise HTTPException(404,"Booking not found")
    service=db.get(Service,b.service_id)
    if not service or (not service.is_active and b.status not in {BookingStatus.STAYING,BookingStatus.CHECKED_IN}):raise HTTPException(409,"Active service required")
    if payload.starts_at is not None or payload.ends_at is not None:
        raise HTTPException(422,"Assignment timing is derived from the booking; use effective time only for handover")
    result=assign(db,b,payload.staff_user_id,user,payload.effective_at)
    db.commit();return result


@router.put("/admin/bookings/{booking_id}/accommodation")
def allocate_accommodation(booking_id: UUID, payload: AllocationIn, user: User = Depends(admin_role), db: Session = Depends(get_db)):
    b = locked_booking(db, booking_id)
    if b.booking_type != ServiceType.BOARDING:
        raise HTTPException(422, "Only Boarding bookings can receive accommodation")
    previous = current_allocations(db, b.id)
    unit_ids = {r.accommodation_id for r in previous} | {payload.accommodation_id}
    units = {r.id: r for r in db.scalars(select(Accommodation).where(Accommodation.id.in_(unit_ids)).order_by(Accommodation.id).with_for_update())}
    unit = units.get(payload.accommodation_id)
    if not unit or not unit.is_active:
        raise HTTPException(409, "Selected accommodation is not active")
    rows = db.scalars(select(BoardingAllocation).where(BoardingAllocation.accommodation_id == unit.id,
        BoardingAllocation.released_at.is_(None), BoardingAllocation.booking_id != b.id)).all()
    if peak_occupancy(rows, b.boarding_start, b.boarding_end) >= unit.capacity:
        raise HTTPException(409, "Accommodation has insufficient capacity for the complete stay")
    old_views = [allocation_view(r) for r in previous]
    for row in previous:
        row.released_at, row.released_by_user_id = utcnow(), user.id
    db.flush()
    row = BoardingAllocation(booking_id=b.id, accommodation_id=unit.id, starts_on=b.boarding_start,
        ends_on=b.boarding_end, created_by_user_id=user.id)
    db.add(row)
    db.flush()
    add_event(db, b, user, "ACCOMMODATION_REALLOCATED" if previous else "ACCOMMODATION_ALLOCATED",
        old_status=b.status, new_status=b.status, details={"old_allocations": old_views, "new_allocation": allocation_view(row)})
    db.commit()
    return allocation_view(row)
