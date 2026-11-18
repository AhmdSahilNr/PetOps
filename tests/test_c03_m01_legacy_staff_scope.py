"""C03-M01 regression: the legacy /staff/bookings/{id} read endpoint follows the same responsibility
read scope as the canonical service routes (PS-03), including a future-effective Boarding handover."""
from datetime import datetime, timedelta, timezone
import app.responsibilities as responsibilities
from tests.conftest import login
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case, grooming, assign, confirm  # noqa: F401  (case is a fixture)
from tests.test_product_simplification import staff_auth, started_stay


def legacy(c, b, auth):
    return c['client'].get(f"/staff/bookings/{b['id']}", headers=auth).status_code


def canonical(c, b, auth):
    return c['client'].get(f"/{b['booking_type'].lower()}/bookings/{b['id']}", headers=auth).status_code


def note(c, b, auth, text):
    return c['client'].post(f"/boarding/bookings/{b['id']}/notes", headers=auth, json={'note': text}).status_code


def unrelated_staff(c):
    r = c['client'].post('/admin/staff', headers=c['admin'], json={
        'display_name': 'Unrelated Fictional Staff', 'email': 'staff.unrelated@petops.example',
        'password': 'DemoPass!123', 'is_active': True})
    assert r.status_code in (200, 201), r.text
    return bearer(login(c['client'], 'staff.unrelated@petops.example', 'DemoPass!123'))


def test_legacy_read_matches_canonical_across_future_boarding_handover(case, monkeypatch):
    c = case
    b = started_stay(c)
    when = datetime.now(timezone.utc) + timedelta(hours=2)
    assign(c, b, staff=c['seed']['staff2'].id, effective_at=when.isoformat())
    old, new, other = staff_auth(c), staff_auth(c, 2), unrelated_staff(c)

    # Before the effective time: the currently responsible Staff keeps read access on BOTH routes,
    # the scheduled Staff can read exactly as on the canonical route, an unrelated Staff cannot.
    assert (legacy(c, b, old), canonical(c, b, old)) == (200, 200)
    assert legacy(c, b, new) == canonical(c, b, new) == 200
    assert (legacy(c, b, other), canonical(c, b, other)) == (404, 404)
    # Mutation authority is still current-responsibility only (not broadened by the read fix).
    assert note(c, b, new, 'Too soon.') == 403
    assert note(c, b, old, 'Still responsible.') == 201
    assert note(c, b, other, 'Not mine.') in (403, 404)

    # At/after the effective time: the new Staff reads and acts; the former Staff is denied on both
    # routes, including a direct (bookmarked) legacy URL.
    later = when + timedelta(minutes=1)
    monkeypatch.setattr(responsibilities, 'utcnow', lambda: later)
    assert (legacy(c, b, new), canonical(c, b, new)) == (200, 200)
    assert (legacy(c, b, old), canonical(c, b, old)) == (404, 404)
    assert (legacy(c, b, other), canonical(c, b, other)) == (404, 404)
    assert note(c, b, old, 'After handover.') in (403, 404)
    # A successful write by the new Staff is not asserted here: the clock is advanced only in the
    # application layer, and the PostgreSQL rules check real database time (clock_timestamp), so the
    # database still correctly refuses a write before the real effective time. The new Staff's write
    # authority after a handover is covered by test_mid_stay_handover_preserves_history_and_access.


def test_legacy_read_after_immediate_grooming_reassignment(case):
    c = case
    b = grooming(c); assign(c, b); confirm(c, b)
    assign(c, b, c['seed']['staff2'].id)
    first, second = staff_auth(c), staff_auth(c, 2)
    assert (legacy(c, b, first), canonical(c, b, first)) == (404, 404)
    assert (legacy(c, b, second), canonical(c, b, second)) == (200, 200)
