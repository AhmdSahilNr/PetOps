"""2026-11-18 product revamp: shell/caching, data minimisation, timelines, operations centre, lodging board,
Insights 2.0 drill-down equality, former-Staff revocation and a route-inventory guard (directives 01-03)."""
import re
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute

from app.database import SessionLocal
from app.availability import boarding_capacity
from app.main import ASSET_VERSION, app
from app.services import business_today
from tests.conftest import login
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case, grooming, boarding, assign, allocate, confirm  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
STAFF_KEYS = {'assigned_staff_user_id', 'assigned_staff_name', 'current_staff_user_id', 'responsibility_periods', 'staff_start', 'staff_end'}


def staff_auth(c, n=1):
    return bearer(login(c['client'], c['seed'][f'staff{n}'].email, 'DemoPass!123'))


# ---------- Shell, caching and static safety ----------

def test_shell_has_csp_versioned_assets_and_revalidated_static(client):
    r = client.get('/')
    assert r.status_code == 200
    assert "script-src 'self'" in r.headers['content-security-policy'] and r.headers['cache-control'] == 'no-store'
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert f'/static/js/app.js?v={ASSET_VERSION}' in r.text and '{{ASSET_VERSION}}' not in r.text
    for href in re.findall(r'(?:href|src)="(/static/[^"?]+)\?v=', r.text):
        s = client.get(href)
        assert s.status_code == 200 and s.headers['cache-control'] == 'no-cache' and s.headers.get('etag'), href
    for legacy in ('/static/index.html', '/static/demo.js', '/static/boarding.js', '/static/refinement.css'):
        assert client.get(legacy).status_code == 404


def test_frontend_modules_are_text_only_and_resolvable():
    js = list((ROOT / 'app/static/js').rglob('*.js'))
    assert len(js) >= 30
    for p in js:
        text = p.read_text(encoding='utf-8')
        for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function'):
            assert banned not in text, f'{p.name} uses {banned}'
        for spec in re.findall(r"""(?:from\s+|import\()\s*['"](\.[^'"]+)['"]""", text):
            assert (p.parent / spec).resolve().exists(), f'{p.name} imports missing {spec}'
    assert not [p for p in (ROOT / 'app/static').iterdir() if p.is_file()], 'no loose legacy files in app/static'
    # QA pass 2 (Q2-01): shipped text must be UTF-8 without BOM and free of mis-decoded sequences such as "â€".
    for p in [*(ROOT / 'app/static').rglob('*.*'), ROOT / 'app/templates/index.html', *(ROOT / 'app').glob('*.py')]:
        raw = p.read_bytes()
        assert not raw.startswith(b'\xef\xbb\xbf'), f'{p.name} has a BOM'
        text = raw.decode('utf-8')
        assert 'â€' not in text and 'Ã' not in text, f'{p.name} contains garbled characters'
    # JS source is pure ASCII (non-ASCII text uses \u escapes), so no editor or shell encoding can garble it.
    for p in (ROOT / 'app/static/js').rglob('*.js'):
        assert all(b < 128 for b in p.read_bytes()), f'{p.name} contains non-ASCII bytes; use \\u escapes'
    for p in (ROOT / 'app/static/css').glob('*.css'):
        assert '@import' not in p.read_text(encoding='utf-8') and 'url(http' not in p.read_text(encoding='utf-8')


# ---------- Customer data minimisation (D4 / directive 03 §38) ----------

def test_customer_responses_carry_no_internal_staffing_or_audit_data(case):
    c = case; b = grooming(c); assign(c, b); confirm(c, b)
    cl, owner = c['client'], c['owner']
    views = [cl.get('/bookings', headers=owner).json()[0], cl.get(f"/bookings/{b['id']}", headers=owner).json(),
             cl.get('/grooming/bookings', headers=owner).json()[0], cl.get(f"/grooming/bookings/{b['id']}", headers=owner).json()['booking']]
    for v in views:
        assert not (STAFF_KEYS & set(v)), v.keys()
    # QA F-13: positive allowlist — the Customer keeps everything their pages need.
    need = {'id', 'pet_id', 'service_id', 'booking_type', 'status', 'created_at', 'grooming_start', 'grooming_duration_minutes', 'boarding_start', 'boarding_end'}
    for v in views:
        assert need <= set(v), need - set(v)
    assert {'pet_name', 'service_name'} <= set(views[2])
    d = cl.get(f"/grooming/bookings/{b['id']}", headers=owner).json()
    assert {'booking', 'pet_name', 'service_name', 'customer_name', 'grooming_record', 'history', 'timeline'} <= set(d)
    assert 'responsibilities' not in d and 'allocation_history' not in d
    assert all(set(e) == {'event_type', 'old_status', 'new_status', 'created_at', 'old_schedule', 'new_schedule'} for e in d['history'])
    assert all(set(e) == {'event_type', 'old_status', 'new_status', 'created_at', 'old_schedule', 'new_schedule'} for e in cl.get(f"/bookings/{b['id']}/history", headers=owner).json())
    # Staff and Admin keep the operational fields they need.
    assert cl.get(f"/grooming/bookings/{b['id']}", headers=staff_auth(c)).json()['booking']['assigned_staff_user_id'] == str(c['seed']['staff1'].id)
    assert cl.get(f"/grooming/bookings/{b['id']}", headers=c['admin']).json()['responsibilities']


def test_customer_boarding_detail_hides_actor_ids_but_keeps_stay_facts(case):
    c = case; b = boarding(c, start=business_today()); allocate(c, b); assign(c, b); confirm(c, b)
    s = staff_auth(c)
    assert c['client'].post(f"/boarding/bookings/{b['id']}/check-in", headers=s, json={}).status_code == 200
    assert c['client'].post(f"/boarding/bookings/{b['id']}/notes", headers=s, json={'note': 'Settled in well.'}).status_code == 201
    d = c['client'].get(f"/boarding/bookings/{b['id']}", headers=c['owner']).json()
    assert d['stay_notes'][0]['note'] == 'Settled in well.' and set(d['stay_notes'][0]) == {'id', 'note', 'created_at'}
    assert d['boarding_stay']['checked_in_at'] and not any(k.endswith('_by_user_id') for k in d['boarding_stay'])
    assert 'accommodation_name' not in d


# ---------- Timeline audiences ----------

def test_timeline_is_role_filtered_and_attributed(case):
    c = case; b = grooming(c); assign(c, b); confirm(c, b)
    cust = c['client'].get(f"/grooming/bookings/{b['id']}", headers=c['owner']).json()['timeline']
    assert [e['kind'] for e in cust] == ['BOOKING_SUBMITTED', 'STATUS_CHANGED']
    assert cust[0]['actor'] == 'You' and cust[1]['actor'] == 'PetOps' and cust[1]['title'] == 'Booking confirmed'
    adm = c['client'].get(f"/admin/bookings/{b['id']}/history", headers=c['admin']).json()['timeline']
    assert [e['kind'] for e in adm] == ['BOOKING_SUBMITTED', 'STAFF_ASSIGNED', 'STATUS_CHANGED']
    assert adm[0]['actor'] == 'Customer' and adm[1]['actor_role'] == 'Admin' and adm[1]['title'] == 'Staff assigned'
    staff = c['client'].get(f"/grooming/bookings/{b['id']}", headers=staff_auth(c)).json()['timeline']
    assert 'STAFF_ASSIGNED' in [e['kind'] for e in staff]
    assign(c, b, staff=c['seed']['staff2'].id)
    adm2 = c['client'].get(f"/admin/bookings/{b['id']}/history", headers=c['admin']).json()['timeline']
    assert adm2[-1]['title'] == 'Staff reassigned'


def test_checkout_records_one_timeline_entry_not_a_technical_duplicate(case):
    c = case; b = boarding(c, start=business_today()); allocate(c, b); confirm(c, b)
    for action in ('check-in', 'check-out'):
        assert c['client'].post(f"/boarding/bookings/{b['id']}/{action}", headers=c['admin'], json={}).status_code == 200
    kinds = [e['kind'] for e in c['client'].get(f"/admin/bookings/{b['id']}/history", headers=c['admin']).json()['timeline']]
    assert kinds.count('BOARDING_CHECKED_OUT') == 1 and 'BOARDING_COMPLETED' not in kinds


# ---------- Former Staff revocation across views (P4 gaps) ----------

@pytest.mark.parametrize('change', ['reassign', 'customer_cancel', 'admin_reschedule'])
def test_former_staff_loses_detail_timeline_and_notification_context(case, change):
    c = case; b = grooming(c); assign(c, b); confirm(c, b)
    old = staff_auth(c)
    assert c['client'].get(f"/grooming/bookings/{b['id']}", headers=old).status_code == 200
    if change == 'reassign':
        assign(c, b, staff=c['seed']['staff2'].id)
    elif change == 'customer_cancel':
        assert c['client'].post(f"/bookings/{b['id']}/cancel", headers=c['owner']).status_code == 200
    else:
        r = c['client'].post(f"/admin/bookings/{b['id']}/reschedule", headers=c['admin'], json={'grooming_start': (c['start'] + timedelta(days=1)).isoformat()})
        assert r.status_code == 200, r.text
    assert c['client'].get(f"/grooming/bookings/{b['id']}", headers=old).status_code == 404
    assert b['id'] not in [x['id'] for x in c['client'].get('/grooming/bookings', headers=old).json()]
    assert c['client'].post(f"/grooming/bookings/{b['id']}/start", headers=old, json={}).status_code in {403, 404}
    for n in c['client'].get('/notifications', headers=old).json()['items']:
        assert n['can_view_booking'] is False and n['pet_name'] is None and n['schedule'] is None


@pytest.mark.parametrize('change', ['reassign_before_arrival', 'handover_during_stay'])
def test_former_boarding_staff_loses_detail_timeline_and_notification_context(case, change):
    """QA F-18: the reassignment invariant for Boarding (directive 03 §9)."""
    c = case; b = boarding(c, start=business_today()); allocate(c, b); assign(c, b); confirm(c, b)
    old = staff_auth(c)
    if change == 'handover_during_stay':
        assert c['client'].post(f"/boarding/bookings/{b['id']}/check-in", headers=old, json={}).status_code == 200
        r = c['client'].put(f"/admin/bookings/{b['id']}/staff", headers=c['admin'], json={'staff_user_id': str(c['seed']['staff2'].id)})
        assert r.status_code == 200, r.text  # effective now
    else:
        assign(c, b, staff=c['seed']['staff2'].id)
    assert c['client'].get(f"/boarding/bookings/{b['id']}", headers=old).status_code == 404
    assert b['id'] not in [x['id'] for x in c['client'].get('/boarding/bookings', headers=old).json()]
    assert c['client'].post(f"/boarding/bookings/{b['id']}/notes", headers=old, json={'note': 'x'}).status_code in {403, 404}
    for n in c['client'].get('/notifications', headers=old).json()['items']:
        assert n['can_view_booking'] is False and n['pet_name'] is None and n['schedule'] is None
    new = c['client'].get(f"/boarding/bookings/{b['id']}", headers=staff_auth(c, 2)).json()
    assert new['timeline'] and new['accommodation_name']


# ---------- Overdue stay (derived display exception; no rule change) ----------

@pytest.mark.parametrize('kind,status,end_offset,expected', [
    ('BOARDING', 'STAYING', 0, False),       # departure today is not overdue
    ('BOARDING', 'STAYING', -1, True),       # past departure, stay still open
    ('BOARDING', 'CHECKED_IN', -3, True),    # legacy open stay
    ('BOARDING', 'CHECKED_OUT', -1, False),  # checked out
    ('BOARDING', 'COMPLETED', -1, False),
    ('BOARDING', 'CANCELLED', -1, False),
    ('BOARDING', 'REJECTED', -1, False),
    ('BOARDING', 'CONFIRMED', -1, False),    # never arrived: not an open stay
    ('BOARDING', 'STAYING', 1, False),       # departs tomorrow
    ('GROOMING', 'IN_PROGRESS', -1, False),
])
def test_overdue_stay_rule(kind, status, end_offset, expected):
    from types import SimpleNamespace
    from datetime import date
    from app.models import BookingStatus, ServiceType
    from app.operations import is_overdue_stay
    today = date(2026, 11, 18)
    b = SimpleNamespace(booking_type=ServiceType[kind], status=BookingStatus[status],
                        boarding_end=today + timedelta(days=end_offset) if kind == 'BOARDING' else None)
    assert is_overdue_stay(b, today) is expected


def test_overdue_stay_uses_the_myt_business_day():
    from datetime import datetime, timezone, date
    from app.services import BUSINESS_TIMEZONE
    assert datetime(2026, 11, 18, 15, 59, 59, tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date() == date(2026, 11, 18)
    assert datetime(2026, 11, 18, 16, 0, 0, tzinfo=timezone.utc).astimezone(BUSINESS_TIMEZONE).date() == date(2026, 11, 19)


def test_active_stay_departing_today_is_listed_but_not_overdue(case):
    c = case; b = boarding(c, start=business_today(), end=business_today() + timedelta(days=1)); allocate(c, b); confirm(c, b)
    assert c['client'].post(f"/boarding/bookings/{b['id']}/check-in", headers=c['admin'], json={}).status_code == 200
    o = c['client'].get('/admin/operations', headers=c['admin']).json()
    row = next(x for x in o['in_care'] if x['id'] == b['id'])
    assert 'past_planned_checkout' not in row['flags']
    board = c['client'].get('/admin/boarding/board', headers=c['admin']).json()
    stay = next(s for u in board['units'] for s in u['stays'] if s['id'] == b['id'])
    assert 'in_care' in stay['flags'] and 'past_planned_checkout' not in stay['flags']


# ---------- Admin read views: authorization ----------

ADMIN_READS = ['/admin/operations', '/admin/boarding/board', '/admin/insights/records?metric=created&from_date=2026-11-01&to_date=2026-11-02']


@pytest.mark.parametrize('path', ADMIN_READS)
def test_new_admin_views_deny_anonymous_customer_and_staff(case, path):
    c = case
    c['client'].cookies.clear()  # the fixture's logins leave a session cookie; anonymous means no cookie and no header
    assert c['client'].get(path).status_code == 401
    assert c['client'].get(path, headers=c['owner']).status_code == 403
    assert c['client'].get(path, headers=staff_auth(c)).status_code == 403
    assert c['client'].get(path, headers=c['admin']).status_code == 200


# ---------- Operations centre definitions ----------

def test_operations_readiness_changed_requests_and_counts_are_lists(case):
    c = case; g = grooming(c); bd = boarding(c)
    ops = lambda: c['client'].get('/admin/operations', headers=c['admin']).json()  # noqa: E731
    flags = lambda o, b: next(x['flags'] for x in o['needs_decision'] if x['id'] == b['id'])  # noqa: E731
    o = ops()
    assert flags(o, g) == ['needs_staff'] and flags(o, bd) == ['needs_accommodation']
    assign(c, g); allocate(c, bd)
    o = ops()
    assert flags(o, g) == ['ready'] and flags(o, bd) == ['ready']
    confirm(c, g)
    o = ops()
    assert g['id'] not in [x['id'] for x in o['needs_decision']]
    assert g['id'] in [x['id'] for x in o['coming_up']]  # confirmed, 5 days ahead
    r = c['client'].post(f"/bookings/{g['id']}/reschedule", headers=c['owner'], json={'grooming_start': (c['start'] + timedelta(days=1)).isoformat()})
    assert r.status_code == 200
    o = ops()
    assert 'changed' in flags(o, g) and g['id'] in [x['id'] for x in o['changed_requests']]
    assert g['id'] not in [x['id'] for x in o['coming_up']], 'old date must not remain upcoming'
    assert set(o['definitions']) >= {'needs_decision', 'arrivals_today', 'departures_due', 'in_care', 'coming_up', 'staff_work'}


def test_operations_arrival_then_in_care_and_staff_work(case):
    c = case; b = boarding(c, start=business_today()); allocate(c, b); assign(c, b); confirm(c, b)
    o = c['client'].get('/admin/operations', headers=c['admin']).json()
    assert [x['id'] for x in o['arrivals_today']] == [b['id']] and not o['in_care']
    me = next(s for s in o['staff_work'] if s['staff_user_id'] == str(c['seed']['staff1'].id))
    assert b['id'] in [x['id'] for x in me['now'] + me['next_7_days']]
    assert c['client'].post(f"/boarding/bookings/{b['id']}/check-in", headers=staff_auth(c), json={}).status_code == 200
    o = c['client'].get('/admin/operations', headers=c['admin']).json()
    assert not o['arrivals_today'] and [x['id'] for x in o['in_care']] == [b['id']]
    assert o['capacity_now']['occupied'] == 1


# ---------- Lodging board ----------

def test_lodging_board_uses_canonical_allocations_and_bounds(case):
    c = case; day = business_today() + timedelta(days=1)
    a = boarding(c, start=day, end=day + timedelta(days=3)); allocate(c, a)
    b2 = boarding(c, start=day + timedelta(days=1), end=day + timedelta(days=2)); allocate(c, b2)
    board = c['client'].get(f'/admin/boarding/board?start={business_today().isoformat()}&nights=7', headers=c['admin']).json()
    unit = next(u for u in board['units'] if u['id'] == str(c['seed']['unit'].id))
    reserved = {n['date']: n['reserved'] for n in unit['nights']}
    assert reserved[business_today().isoformat()] == 0 and reserved[day.isoformat()] == 1 and reserved[(day + timedelta(days=1)).isoformat()] == 2
    assert reserved[(day + timedelta(days=3)).isoformat()] == 0, 'check-out date is excluded'
    with SessionLocal() as db:
        canonical = next(r for r in boarding_capacity(db, business_today(), business_today() + timedelta(days=7)) if r['accommodation_id'] == str(c['seed']['unit'].id))
    assert unit['peak_reserved'] == canonical['peak_occupancy'] == max(reserved.values())
    past = c['client'].get(f'/admin/boarding/board?start={(business_today() - timedelta(days=5)).isoformat()}', headers=c['admin']).json()
    assert past['start'] == business_today().isoformat(), 'past nights are not reconstructed'
    for bad in (0, 32):
        assert c['client'].get(f'/admin/boarding/board?nights={bad}', headers=c['admin']).status_code == 422


# ---------- Insights 2.0: every count equals its drill-down ----------

def test_insights_counts_equal_records_and_trend_is_zero_filled(case):
    c = case
    g1 = grooming(c); assign(c, g1); confirm(c, g1)
    s = staff_auth(c)
    assert c['client'].post(f"/grooming/bookings/{g1['id']}/start", headers=s, json={}).status_code == 200
    assert c['client'].post(f"/grooming/bookings/{g1['id']}/complete", headers=s, json={'service_notes': 'Done.'}).status_code == 200
    g2 = grooming(c, start=c['start'] + timedelta(days=1))
    assert c['client'].post(f"/admin/bookings/{g2['id']}/status", headers=c['admin'], json={'status': 'REJECTED'}).status_code == 200
    bd = boarding(c); allocate(c, bd); confirm(c, bd)
    assert c['client'].post(f"/bookings/{bd['id']}/cancel", headers=c['owner']).status_code == 200
    g3 = grooming(c, start=c['start'] + timedelta(days=2))
    for k in (3, 4):
        assert c['client'].post(f"/bookings/{g3['id']}/reschedule", headers=c['owner'], json={'grooming_start': (c['start'] + timedelta(days=k)).isoformat()}).status_code == 200
    today = business_today(); frm = (today - timedelta(days=6)).isoformat(); to = today.isoformat()
    d = c['client'].get(f'/admin/dashboard?from_date={frm}&to_date={to}', headers=c['admin']).json()
    rec = lambda m, **kw: c['client'].get('/admin/insights/records', headers=c['admin'], params={'metric': m, 'from_date': frm, 'to_date': to, **kw}).json()['total']  # noqa: E731
    assert rec('created') == d['total_bookings'] == 4
    assert rec('completed') == sum(d['completed_services_by_type'].values()) == 1
    assert rec('cancellations') == d['booking_change_events']['BOOKING_CANCELLED'] == 1
    assert rec('reschedules') == d['booking_change_events']['BOOKING_RESCHEDULED'] == 2
    assert d['period_totals']['rescheduled_bookings'] == 1, 'one booking rescheduled twice'
    assert rec('decisions_confirmed') == d['confirmation_decisions']['confirmed']
    assert rec('decisions_rejected') == d['confirmation_decisions']['rejected'] == 1
    for status, n in d['bookings_by_status'].items():
        if n:
            assert rec('created', status=status) == n, status
    assert rec('created', service_type='GROOMING') == d['bookings_by_type']['GROOMING']
    t = d['trend']
    assert t['bucket_size'] == 'day' and len(t['buckets']) == 7 and t['zero_filled']
    assert sum(b['created_grooming'] + b['created_boarding'] for b in t['buckets']) == d['total_bookings']
    assert sum(b['reschedules'] for b in t['buckets']) == 2
    prev = d['previous_period']
    assert prev['to_date'] == (today - timedelta(days=7)).isoformat() and prev['bookings_created'] == 0 and prev['decision_rate_percent'] is None
    long = c['client'].get(f'/admin/dashboard?from_date={(today - timedelta(days=800)).isoformat()}&to_date={to}', headers=c['admin']).json()
    assert long['trend'] is None
    assert c['client'].get('/admin/insights/records', headers=c['admin'], params={'metric': 'revenue', 'from_date': frm, 'to_date': to}).status_code == 422


# ---------- Route inventory (N1): every route is classified and guarded ----------

PUBLIC = {('GET', '/'), ('GET', '/health'), ('POST', '/auth/register'), ('POST', '/auth/login')}


def test_every_route_is_classified_and_admin_routes_refuse_customers(case):
    c = case
    seen = 0
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    for inc in app.routes:  # newer FastAPI wraps included routers
        if hasattr(inc, 'original_router'):
            routes += [r for r in inc.original_router.routes if isinstance(r, APIRoute)]
    for route in routes:
        for method in route.methods - {'HEAD', 'OPTIONS'}:
            path = re.sub(r'\{[^}]+\}', str(uuid4()), route.path)
            seen += 1
            c['client'].cookies.clear()
            anon = c['client'].request(method, path, json={})
            if (method, route.path) in PUBLIC:
                continue
            assert anon.status_code == 401, f'{method} {route.path} must require sign-in (got {anon.status_code})'
            if route.path.startswith('/admin'):
                r = c['client'].request(method, path, json={}, headers=c['owner'])
                assert r.status_code == 403, f'{method} {route.path} must refuse Customers (got {r.status_code})'
    assert seen >= 70
