"""Shared booking/event representation; no additional authorization surface."""
from .models import Booking
from .services import utc_iso


def booking_view(b: Booking):
    from sqlalchemy.orm import object_session
    from .models import ServiceType,User
    from .responsibilities import current_staff,rows_for,view
    db=object_session(b)
    responsible=current_staff(db,b) if db and b.booking_type==ServiceType.BOARDING else b.assigned_staff_user_id
    person=db.get(User,responsible or b.assigned_staff_user_id) if db and (responsible or b.assigned_staff_user_id) else None
    return {
        "assigned_staff_name":person.display_name or 'Name not recorded' if person else None,
        "current_staff_user_id":str(responsible) if responsible else None,
        "responsibility_periods":[view(db,row) for row in rows_for(db,b.id)] if db else [],
        "id": str(b.id), "customer_id": str(b.customer_id), "pet_id": str(b.pet_id), "service_id": str(b.service_id),
        "booking_type": b.booking_type.value, "status": b.status.value, "created_at": utc_iso(b.created_at),
        "grooming_start": utc_iso(b.grooming_start),
        "grooming_duration_minutes": b.grooming_duration_minutes,
        "staff_start": utc_iso(b.staff_start), "staff_end": utc_iso(b.staff_end),
        "boarding_start": b.boarding_start.isoformat() if b.boarding_start else None,
        "boarding_end": b.boarding_end.isoformat() if b.boarding_end else None,
        "assigned_staff_user_id": str(b.assigned_staff_user_id) if b.assigned_staff_user_id else None,
    }


def event_view(e):
    return {"event_type": e.event_type, "old_status": e.old_status.value if e.old_status else None,
        "new_status": e.new_status.value if e.new_status else None, "actor_user_id": str(e.actor_user_id),
        "created_at": utc_iso(e.created_at), "old_schedule": e.old_schedule, "new_schedule": e.new_schedule,
        "old_assigned_staff_user_id": str(e.old_assigned_staff_user_id) if e.old_assigned_staff_user_id else None,
        "new_assigned_staff_user_id": str(e.new_assigned_staff_user_id) if e.new_assigned_staff_user_id else None,
        "details": e.details}
