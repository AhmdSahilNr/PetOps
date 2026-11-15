"""Bounded final-candidate reporting/fixture checks; disposable PostgreSQL only."""
from datetime import date, datetime, timedelta, timezone
from uuid import UUID
import pytest
from sqlalchemy import select, func, update

from app.database import SessionLocal
from app.models import Booking, BookingEvent
from app.services import business_today
from scripts.final_demo import plan, validate_target
from tests.conftest import login
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case, grooming, boarding, assign, allocate, confirm
from tests.test_slice5 import call, report


def test_confirmation_uses_decisions_not_current_status_or_unique_bookings(case):
    c = case
    changed = grooming(c); assign(c, changed); confirm(c, changed)
    call(c, 'POST', f"/bookings/{changed['id']}/reschedule", {'grooming_start': (c['start'] + timedelta(days=1)).isoformat()}, who='owner')
    assign(c, changed); confirm(c, changed)
    call(c, 'POST', f"/bookings/{changed['id']}/cancel", who='owner')
    rejected = grooming(c, start=c['start'] + timedelta(days=2))
    call(c, 'POST', f"/admin/bookings/{rejected['id']}/status", {'status': 'REJECTED'})
    grooming(c, start=c['start'] + timedelta(days=3))
    done = grooming(c, start=c['start'] + timedelta(days=4)); assign(c, done); confirm(c, done)
    call(c, 'POST', f"/grooming/bookings/{done['id']}/start", {})
    call(c, 'POST', f"/grooming/bookings/{done['id']}/complete", {'service_notes': 'Controlled fictional test'})
    d = report(c)
    assert d['total_bookings'] == 4 and d['bookings_by_status']['CONFIRMED'] == 0
    assert d['confirmation_decisions'] == {'confirmed': 3, 'rejected': 1, 'decided': 4, 'confirmation_rate_percent': 75.0}
    assert d['completed_services_by_type'] == {'GROOMING': 1, 'BOARDING': 0}
    assert d['booking_change_events'] == {'BOOKING_CANCELLED': 1, 'BOOKING_RESCHEDULED': 1}


def test_empty_period_has_no_invented_rate_or_trend(case):
    d = report(case)
    assert d['confirmation_decisions']['confirmation_rate_percent'] is None
    assert d['confirmation_decisions']['decided'] == 0
    assert d['booking_volume'] == {'bucket_size': 'week', 'buckets': [], 'zero_buckets_omitted': True}


def set_test_created_at(b, when):
    # Only controlled test rows; final_demo never edits timestamps/history/status by SQL.
    with SessionLocal() as db:
        db.execute(update(Booking).where(Booking.id == UUID(b['id'])).values(created_at=when))
        db.commit()


def test_myt_inclusive_day_and_week_bucket_boundaries(case):
    c = case
    timestamps = [datetime(2026, 11, 1, 15, 59, 59, tzinfo=timezone.utc),
                  datetime(2026, 11, 1, 16, 0, tzinfo=timezone.utc),
                  datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)]
    for i, stamp in enumerate(timestamps):
        b = grooming(c, start=c['start'] + timedelta(days=i)); set_test_created_at(b, stamp)
    d = report(c, date(2026, 11, 2), date(2026, 11, 2))
    assert d['total_bookings'] == 1
    assert d['booking_volume']['buckets'] == [{'period_start': '2026-11-02', 'GROOMING': 1, 'BOARDING': 0, 'total': 1}]
    assert d['period']['utc_start'].startswith('2026-11-01T16:00:00')
    assert d['period']['utc_end_exclusive'].startswith('2026-11-02T16:00:00')


def test_decision_period_is_independent_of_request_created_cohort(case):
    c = case; b = grooming(c)
    set_test_created_at(b, datetime.now(timezone.utc) - timedelta(days=14))
    assign(c, b); confirm(c, b)
    d = report(c)
    assert d['total_bookings'] == 0
    assert d['confirmation_decisions']['confirmed'] == 1
    assert d['confirmation_decisions']['confirmation_rate_percent'] == 100.0


def test_long_period_monthly_volume_reconciles_types_and_total(case):
    c = case; g = grooming(c); b = boarding(c)
    set_test_created_at(g, datetime(2026, 10, 10, 3, tzinfo=timezone.utc))
    set_test_created_at(b, datetime(2026, 11, 3, 3, tzinfo=timezone.utc))
    d = report(c, date(2026, 9, 1), date(2026, 12, 31))
    assert d['booking_volume']['bucket_size'] == 'month'
    assert [v['period_start'] for v in d['booking_volume']['buckets']] == ['2026-10-01', '2026-11-01']
    assert sum(v['total'] for v in d['booking_volume']['buckets']) == d['total_bookings'] == 2
    assert sum(v['GROOMING'] for v in d['booking_volume']['buckets']) == d['bookings_by_type']['GROOMING'] == 1
    assert sum(v['BOARDING'] for v in d['booking_volume']['buckets']) == d['bookings_by_type']['BOARDING'] == 1


def test_next_seven_days_is_labeled_independent_and_excludes_pending_cancelled(case):
    c = case; g = grooming(c); assign(c, g); confirm(c, g)
    b = boarding(c); allocate(c, b); confirm(c, b)
    grooming(c, start=c['start'] + timedelta(hours=2))
    now = report(c)['next_seven_days']
    assert now['grooming_appointments'] == 1
    assert now['boarding_arrivals'] == now['boarding_departures'] == 1
    assert now['active_boarding_stays'] == 0 and now['requests_needing_review'] == 1
    past = report(c, business_today() - timedelta(days=10), business_today() - timedelta(days=9))
    assert past['total_bookings'] == 0 and past['next_seven_days'] == now
    call(c, 'POST', f"/bookings/{b['id']}/cancel", who='owner')
    assert report(c)['next_seven_days']['boarding_arrivals'] == 0


@pytest.mark.parametrize('role,expected', [('anonymous', 401), ('owner', 403), ('staff', 403)])
def test_reporting_and_reminder_configuration_stay_admin_only(case, role, expected):
    c = case
    c['staff'] = bearer(login(c['client'], c['seed']['staff1'].email, 'DemoPass!123'))
    c['client'].cookies.clear()
    headers = {} if role == 'anonymous' else c[role]
    today = business_today()
    for path in [f'/admin/dashboard?from_date={today}&to_date={today}', '/admin/notification-settings']:
        assert c['client'].get(path, headers=headers).status_code == expected


def test_reporting_gets_do_not_append_business_history(case):
    c = case; grooming(c)
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(BookingEvent))
    for _ in range(3): report(c)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BookingEvent)) == before


@pytest.mark.parametrize('url', [
    'postgresql+psycopg://x:y@127.0.0.1/petops_final_dev_upgrade_test',
    'postgresql+psycopg://x:y@127.0.0.1/petops_repro_demo_test',
    'postgresql+psycopg://x:y@remote.example/petops_final_candidate_demo_test',
    'postgresql+psycopg://x:y@127.0.0.1/petops_final_candidate_verify_test',
    'postgresql+psycopg://x:y@127.0.0.1/petops_final_candidate_demo_test?options=unsafe',
    'sqlite:///petops_final_candidate_demo_test',
])
def test_demo_guard_rejects_uat_other_databases_remote_and_query_override(url):
    with pytest.raises(ValueError): validate_target(url)


def test_demo_plan_has_reserved_identities_supported_fields_and_coherent_totals():
    p = plan(date(2026, 11, 15))
    assert len(p['accounts']) == 8 and all(a['email'].endswith('@petops.example') for a in p['accounts'])
    assert len(p['pets']) == len(set(p['pets'])) == 8
    assert all(s['duration_minutes'] is None for s in p['services'] if s['type'] == 'BOARDING')
    assert sum(p['expected']['statuses'].values()) == sum(p['expected']['types'].values()) == 17
    assert all(s['duration_minutes'] in {30, 60} for s in p['services'] if s['type'] == 'GROOMING')
    assert validate_target('postgresql+psycopg://x:y@127.0.0.1:55432/petops_final_candidate_demo_test').database == p['database']
