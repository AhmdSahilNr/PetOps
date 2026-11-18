"""Regression coverage for defects fixed in the 2026-11-17 final-candidate pass."""
import re
from pathlib import Path
from uuid import UUID
from app.database import SessionLocal
from app.models import Booking, User
from app.grooming_routes import holds_open_responsibility
from tests.conftest import login
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case, grooming, boarding, assign, allocate, confirm

ROOT = Path(__file__).resolve().parents[1]


def staff_auth(c, number=1):
    return bearer(login(c['client'], c['seed'][f'staff{number}'].email, 'DemoPass!123'))


def post(c, b, action, auth):
    return c['client'].post(f"/grooming/bookings/{b['id']}/{action}", headers=auth, json={})


def test_reassigned_grooming_staff_cannot_start_or_complete(case):
    c = case; b = grooming(c); assign(c, b); confirm(c, b)
    old, new = staff_auth(c), staff_auth(c, 2)
    assign(c, b, staff=c['seed']['staff2'].id)
    # Former Staff is refused (scope 404 or responsibility 403); no state change.
    assert post(c, b, 'start', old).status_code in {403, 404}
    r = post(c, b, 'start', new); assert r.status_code == 200, r.text
    assert post(c, b, 'complete', old).status_code in {403, 404}
    r = post(c, b, 'complete', new); assert r.status_code == 200, r.text
    assert r.json()['booking']['status'] == 'COMPLETED'


def test_open_responsibility_helper_follows_reassignment(case):
    c = case; b = grooming(c); assign(c, b); confirm(c, b)
    with SessionLocal() as db:
        row = db.get(Booking, UUID(b['id'])); s1 = db.get(User, c['seed']['staff1'].id); s2 = db.get(User, c['seed']['staff2'].id)
        assert holds_open_responsibility(db, row, s1) and not holds_open_responsibility(db, row, s2)
    assign(c, b, staff=c['seed']['staff2'].id)
    with SessionLocal() as db:
        row = db.get(Booking, UUID(b['id'])); s1 = db.get(User, c['seed']['staff1'].id); s2 = db.get(User, c['seed']['staff2'].id)
        assert not holds_open_responsibility(db, row, s1) and holds_open_responsibility(db, row, s2)


def test_admin_still_operates_grooming_without_responsibility(case):
    c = case; b = grooming(c); assign(c, b); confirm(c, b)
    r = post(c, b, 'start', c['admin']); assert r.status_code == 200, r.text
    r = post(c, b, 'complete', c['admin']); assert r.status_code == 200, r.text


def test_former_staff_notification_hides_pet_service_and_schedule(case):
    c = case; b = grooming(c); assign(c, b); old = staff_auth(c)
    before = c['client'].get('/notifications', headers=old).json()['items'][0]
    assert before['pet_name'] and before['schedule']
    assign(c, b, staff=c['seed']['staff2'].id)
    for n in c['client'].get('/notifications', headers=old).json()['items']:
        assert n['can_view_booking'] is False and n['cta_label'] is None
        assert n['pet_name'] is None and n['service_name'] is None and n['schedule'] is None
        assert n['title'] == 'Booking update'
    # The new responsible Staff and the Customer keep full context.
    new_item = c['client'].get('/notifications', headers=staff_auth(c, 2)).json()['items'][0]
    assert new_item['can_view_booking'] and new_item['pet_name']
    owner_items = c['client'].get('/notifications', headers=c['owner']).json()['items']
    assert owner_items and all(n['can_view_booking'] for n in owner_items)


def test_boarding_staff_assignment_accepts_staff_only_payload(case):
    c = case; b = boarding(c); allocate(c, b)
    r = c['client'].put(f"/admin/bookings/{b['id']}/staff", headers=c['admin'],
                        json={'staff_user_id': str(c['seed']['staff1'].id)})
    assert r.status_code == 200, r.text


def test_boarding_admin_form_does_not_send_derived_duty_times():
    # Re-pointed 2026-11-18: the legacy boarding.js form was retired. Every Admin assignment now goes through the
    # single payload builder (admin/payloads.js); its behaviour is exercised by tests/ui_revamp.mjs, and statically:
    src = (ROOT / 'app/static/js/admin/payloads.js').read_text(encoding='utf-8')
    assert 'starts_at' not in src and 'ends_at' not in src
    callers = [p for p in (ROOT / 'app/static/js').rglob('*.js') if '/staff`' in p.read_text(encoding='utf-8')]
    for p in callers:
        text = p.read_text(encoding='utf-8')
        for m in re.finditer(r"put\(`/admin/bookings/\$\{[^}]+\}/staff`([^;]*);", text):
            assert 'staffAssignmentPayload(' in m.group(1), f'{p.name} must build assignment payloads with staffAssignmentPayload'
