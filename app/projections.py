"""Role-specific response projections (data minimisation, directive 03 §38).

Customers own their bookings but do not need internal staffing or audit data:
Staff identities, responsibility periods, actor ids, allocation history or raw
event details. These projections only REMOVE fields from existing responses;
they never add data and never change authorization (scope is still enforced by
the queries that load the records).
"""

CUSTOMER_HIDDEN_BOOKING_KEYS = frozenset({
    'assigned_staff_user_id', 'assigned_staff_name', 'current_staff_user_id',
    'responsibility_periods', 'staff_start', 'staff_end',
})
CUSTOMER_EVENT_KEYS = ('event_type', 'old_status', 'new_status', 'created_at', 'old_schedule', 'new_schedule')


def customer_booking(view: dict) -> dict:
    return {k: v for k, v in view.items() if k not in CUSTOMER_HIDDEN_BOOKING_KEYS}


def customer_event(event: dict) -> dict:
    return {k: event.get(k) for k in CUSTOMER_EVENT_KEYS}


def customer_detail(detail: dict) -> dict:
    out = {k: v for k, v in detail.items() if k not in {'responsibilities', 'allocation_history', 'history'}}
    out['booking'] = customer_booking(detail['booking'])
    out['history'] = [customer_event(e) for e in detail.get('history', [])]
    record = detail.get('grooming_record')
    if record is not None:
        out['grooming_record'] = {k: record[k] for k in ('id', 'booking_id', 'started_at', 'completed_at', 'service_notes')}
    stay = detail.get('boarding_stay')
    if stay is not None:
        out['boarding_stay'] = {k: stay[k] for k in ('id', 'booking_id', 'checked_in_at', 'stay_started_at', 'checked_out_at', 'completed_at')}
    if 'stay_notes' in detail:
        out['stay_notes'] = [{'id': n['id'], 'note': n['note'], 'created_at': n['created_at']} for n in detail['stay_notes']]
    return out
