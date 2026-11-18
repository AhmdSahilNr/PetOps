"""Unified, role-filtered booking timeline built only from recorded events.

Audiences:
  customer - own booking; customer-language titles; actor shown as "You" or "PetOps";
             internal preparation events (Staff/accommodation) are not shown.
  staff    - scoped booking (caller enforces scope); colleague names shown; Customer shown as "Customer".
  admin    - all events with actor name and role.
Technical events that duplicate another entry (automatic completion recorded with
check-out) are omitted. Nothing here changes data or authorization.
"""
from .models import Accommodation, BookingEvent, BoardingAllocation, BoardingNote, Customer, GroomingRecord, User
from .services import utc_iso

STATUS_TITLES = {'CONFIRMED': 'Booking confirmed', 'REJECTED': 'Request rejected'}
CUSTOMER_TITLES = {
    'BOOKING_SUBMITTED': 'Booking requested', 'BOOKING_RESCHEDULED': 'Dates changed',
    'BOOKING_CANCELLED': 'Booking cancelled', 'GROOMING_STARTED': 'Grooming started',
    'GROOMING_COMPLETED': 'Grooming completed', 'BOARDING_CHECKED_IN': 'Checked in',
    'BOARDING_STAY_STARTED': 'Stay started', 'BOARDING_STAY_UPDATED': 'Stay update',
    'BOARDING_CHECKED_OUT': 'Checked out', 'BOARDING_COMPLETED': 'Stay completed',
}
INTERNAL_EVENTS = {'STAFF_ASSIGNED', 'STAFF_UNASSIGNED', 'ACCOMMODATION_ALLOCATED', 'ACCOMMODATION_REALLOCATED'}
TONE = {'CONFIRMED': 'success', 'REJECTED': 'danger', 'BOOKING_CANCELLED': 'danger', 'GROOMING_COMPLETED': 'success',
        'BOARDING_CHECKED_OUT': 'success', 'BOARDING_COMPLETED': 'success', 'BOOKING_RESCHEDULED': 'warning'}


def _person(db, user_id, cache):
    if user_id is None:
        return None
    if user_id not in cache:
        cache[user_id] = db.get(User, user_id)
    return cache[user_id]


def _name(user):
    if user is None:
        return None
    if user.role.value == 'CUSTOMER':
        return 'Customer'
    return user.display_name or user.email


def build(db, booking, audience):
    if audience not in {'customer', 'staff', 'admin'}:
        raise ValueError('Unknown timeline audience')
    from sqlalchemy import select
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id)
                        .order_by(BookingEvent.created_at, BookingEvent.id)).all()
    owner_user_id = db.get(Customer, booking.customer_id).user_id
    people = {}
    notes = {str(n.event_id): n.note for n in db.scalars(select(BoardingNote).where(
        BoardingNote.event_id.in_([e.id for e in events])))} if events else {}
    record = db.scalar(select(GroomingRecord).where(GroomingRecord.booking_id == booking.id))
    entries = []
    for e in events:
        kind = e.event_type
        details = e.details or {}
        if kind == 'BOARDING_COMPLETED' and details.get('automatic_with_checkout'):
            continue  # recorded together with check-out; one human action, one entry
        if audience == 'customer' and kind in INTERNAL_EVENTS:
            continue
        status = e.new_status.value if e.new_status else None
        title = STATUS_TITLES.get(status, 'Status updated') if kind == 'STATUS_CHANGED' else CUSTOMER_TITLES.get(kind)
        body = None
        actor = _person(db, e.actor_user_id, people)
        if kind in {'STAFF_ASSIGNED', 'STAFF_UNASSIGNED'}:
            old = _person(db, e.old_assigned_staff_user_id, people)
            new = _person(db, e.new_assigned_staff_user_id, people)
            if kind == 'STAFF_UNASSIGNED':
                title = 'Staff assignment removed'
                body = f'{_name(old)} is no longer assigned' if old else None
            elif old and new and old.id != new.id:
                title = 'Staff reassigned'
                body = f'{_name(old)} to {_name(new)}'
                if details.get('effective_at') and e.new_status and e.new_status.value in {'STAYING', 'CHECKED_IN'}:
                    body += ' (handover)'
            else:
                title = 'Staff assigned'
                body = _name(new)
        elif kind in {'ACCOMMODATION_ALLOCATED', 'ACCOMMODATION_REALLOCATED'}:
            title = 'Accommodation reallocated' if kind.endswith('REALLOCATED') else 'Accommodation allocated'
            new_alloc = (details.get('new_allocation') or {}).get('accommodation_id')
            unit = db.get(Accommodation, __import__('uuid').UUID(new_alloc)) if new_alloc else None
            body = unit.name if unit else None
        elif kind == 'STATUS_CHANGED' and status == 'REJECTED' and audience == 'customer':
            title = 'Request not accepted'
        elif kind == 'BOOKING_RESCHEDULED':
            body = 'Returned to Requested for a new decision'
        elif kind == 'BOARDING_STAY_UPDATED':
            body = notes.get(str(e.id))
        elif kind == 'GROOMING_COMPLETED' and record is not None:
            body = record.service_notes
        if title is None:
            title = 'Booking updated'
        if audience == 'customer':
            who = 'You' if e.actor_user_id == owner_user_id else 'PetOps'
            role = None
        else:
            who = _name(actor) or 'Not recorded'
            role = actor.role.value.title() if actor else None
        entries.append({'at': utc_iso(e.created_at), 'kind': kind, 'status': status, 'title': title, 'body': body,
                        'actor': who, 'actor_role': role, 'tone': TONE.get(status if kind == 'STATUS_CHANGED' else kind, 'neutral'),
                        'old_schedule': e.old_schedule if kind == 'BOOKING_RESCHEDULED' else None,
                        'new_schedule': e.new_schedule if kind == 'BOOKING_RESCHEDULED' else None})
    return entries


def current_accommodation_name(db, booking_id):
    from sqlalchemy import select
    from uuid import UUID
    booking_id = booking_id if isinstance(booking_id, UUID) else UUID(str(booking_id))
    row = db.scalar(select(BoardingAllocation).where(BoardingAllocation.booking_id == booking_id,
                                                     BoardingAllocation.released_at.is_(None)))
    if row is None:
        return None
    unit = db.get(Accommodation, row.accommodation_id)
    return unit.name if unit else None
