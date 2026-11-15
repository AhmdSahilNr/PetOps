"""Opt-in fictional final-candidate story on ONE owned loopback database.

Default is a plan only. Apply uses supported APIs after Admin bootstrap.
No status/history/time SQL, real identities, clock patching or UAT target.
"""
import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import time as clock
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo
from sqlalchemy.engine import make_url

DATABASE = 'petops_final_candidate_demo_test'
MARKER = 'petops-final-candidate-demo-v1'
ADMIN_ID = uuid5(NAMESPACE_URL, 'petops-final-candidate-demo-admin')
PASSWORD = 'DemoPass!123'  # Public fictional demonstration password only.
ADMIN = ('farah.ismail@petops.example', 'Farah Ismail')
STAFF = [('daniel.tan@petops.example', 'Daniel Tan'),
         ('aisyah.rahman@petops.example', 'Aisyah Rahman'),
         ('amir.hakim@petops.example', 'Amir Hakim')]
CUSTOMERS = [('nadia.zainal@petops.example', 'Nadia Zainal', ['Milo', 'Coco']),
             ('mei.ling@petops.example', 'Yong Mei Ling', ['Luna', 'Mochi']),
             ('arif.hakim@petops.example', 'Arif Hakim', ['Simba', 'Oreo']),
             ('maya.krishnan@petops.example', 'Maya Krishnan', ['Poppy', 'Kiki'])]
EMAILS = {ADMIN[0], *(s[0] for s in STAFF), *(c[0] for c in CUSTOMERS)}
SERVICES = [('Basic Grooming', 'GROOMING', 30, 10),
            ('Full Grooming', 'GROOMING', 60, 20),
            ('Bath & Blow Dry', 'GROOMING', 30, 30),
            ('Standard Boarding', 'BOARDING', None, 10)]


class DemoStepError(RuntimeError):
    pass


def validate_target(raw):
    u = make_url(raw)
    if u.drivername != 'postgresql+psycopg' or u.host not in {'127.0.0.1', 'localhost'} or u.database != DATABASE or u.query:
        raise ValueError('Only the explicitly named loopback final-demo database is permitted')
    return u


def plan(anchor):
    return {'fixture': MARKER, 'database': DATABASE, 'anchor_date_myt': anchor.isoformat(),
            'fictional_only': True,
            'accounts': [{'email': ADMIN[0], 'display_name': ADMIN[1], 'role': 'ADMIN'}] +
                        [{'email': e, 'display_name': n, 'role': 'STAFF'} for e, n in STAFF] +
                        [{'email': e, 'display_name': n, 'role': 'CUSTOMER'} for e, n, _ in CUSTOMERS],
            'pets': [p for _, _, pets in CUSTOMERS for p in pets],
            'services': [{'name': n, 'type': t, 'duration_minutes': d, 'display_order': o} for n, t, d, o in SERVICES],
            'accommodations': [{'name': 'Garden Suite', 'category': 'Garden', 'capacity': 3},
                               {'name': 'Quiet Suite', 'category': 'Quiet', 'capacity': 2}],
            'expected': {'users': 8, 'pets': 8, 'bookings': 17,
                         'types': {'GROOMING': 9, 'BOARDING': 8},
                         'statuses': {'SUBMITTED': 4, 'CONFIRMED': 5, 'STAYING': 2, 'COMPLETED': 3, 'CANCELLED': 2, 'REJECTED': 1},
                         'completed': {'GROOMING': 2, 'BOARDING': 1},
                         'cancellations': 2, 'reschedules': 2, 'confirmed_decisions': 13, 'rejected_decisions': 1,
                         'occupied_places': 2, 'active_capacity': 5},
            'limits': ['Apply anchor must be the actual MYT date so present stays use valid arrival dates.',
                       'Accelerated fictional lifecycle actions have actual timestamps; not elapsed-care or human-UAT evidence.',
                       'Requests/events are created at seed time: no historical trend points invented.',
                       'Story, ordering and relative schedules repeat; generated IDs, hashes, sessions and timestamps vary.',
                       'Existing UAT, .repro fixture and private portfolio are never selected.']}


def apply(raw, anchor, reset=False):
    validate_target(raw)
    zone = ZoneInfo('Asia/Kuala_Lumpur')
    if anchor != datetime.now(zone).date():
        raise ValueError('Apply requires today in MYT; historical/future clocks are not simulated')
    os.environ['PETOPS_DATABASE_URL'] = raw
    os.environ['PETOPS_REMINDER_POLL_SECONDS'] = '0'
    from sqlalchemy import create_engine, text
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'alembic'))
    if ScriptDirectory.from_config(cfg).get_current_head() != '0008':
        raise ValueError('Review demo for a changed migration head before applying')
    engine = create_engine(raw)
    with engine.connect() as db:
        actual, address = db.execute(text('SELECT current_database(),host(inet_server_addr())')).one()
        if actual != DATABASE or address not in {'127.0.0.1', '::1'}:
            raise ValueError('Resolved database is not the dedicated loopback target')
        marker = db.execute(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")).scalar_one()
        exists = db.execute(text("SELECT to_regclass('public.users')")).scalar_one()
        if marker not in (None, MARKER):
            raise ValueError('Database has a different ownership marker')
        if exists:
            users = db.execute(text('SELECT id,email FROM users')).all()
            if not reset:
                raise ValueError('Existing schema retained; use --reset --apply only for this owned fictional fixture')
            if marker != MARKER or not users or not {e for _, e in users} <= EMAILS or (ADMIN_ID, ADMIN[0]) not in users:
                raise ValueError('Reset refused: marker or exact fictional account ownership differs')
        else:
            if reset or db.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")).scalar_one():
                raise ValueError('Fresh apply requires an empty database; reset requires an owned fixture')
    command.upgrade(cfg, 'head')
    with engine.begin() as db:
        if db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != '0008':
            raise ValueError('Unexpected migration version')
        db.execute(text("COMMENT ON DATABASE petops_final_candidate_demo_test IS 'petops-final-candidate-demo-v1'"))
        if reset:
            db.execute(text('TRUNCATE staff_responsibilities,management_events,notifications,notification_settings,boarding_notes,boarding_stays,grooming_records,boarding_allocations,booking_events,bookings,staff_availability,accommodations,services,pets,customers,user_sessions,users'))
            db.execute(text('INSERT INTO notification_settings(id,enabled) VALUES (1,false)'))
    from app.database import SessionLocal, reset_database_caches
    reset_database_caches()
    from app.models import User, Role
    from app.security import hash_password
    with SessionLocal() as db:
        db.add(User(id=ADMIN_ID, email=ADMIN[0], password_hash=hash_password(PASSWORD), role=Role.ADMIN, display_name=ADMIN[1]))
        db.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    story = []
    with TestClient(app) as client:
        def call(method, path, body=None, token=None):
            r = client.request(method, path, json=body, headers={'Authorization': 'Bearer ' + token} if token else {})
            if r.status_code not in {200, 201, 204}:
                raise DemoStepError(f'Demo API refused ({r.status_code}) at {method} {path}; partial fixture retained')
            return None if r.status_code == 204 else r.json()
        def login(email):
            return call('POST', '/auth/login', {'email': email, 'password': PASSWORD})['token']
        admin = login(ADMIN[0])
        staff = [call('POST', '/admin/staff', {'email': e, 'password': PASSWORD, 'display_name': n}, admin) for e, n in STAFF]
        staff_tokens = [login(e) for e, _ in STAFF]
        services = [call('POST', '/admin/services', {'name': n, 'service_type': t, 'duration_minutes': d, 'display_order': o}, admin) for n, t, d, o in SERVICES]
        units = [call('POST', '/admin/accommodations', {**u, 'is_active': True}, admin) for u in plan(anchor)['accommodations']]
        owners, pets = [], []
        for email, name, names in CUSTOMERS:
            call('POST', '/auth/register', {'email': email, 'password': PASSWORD, 'display_name': name})
            owner = login(email); owners.append(owner)
            pets.append([call('POST', '/pets', {'name': n}, owner) for n in names])
        def scheduled(day, hour):
            return datetime.combine(anchor + timedelta(days=day), time(hour), zone).isoformat()
        def create(label, owner, pet, service, day=0, hour=10, stay=2, instant=None):
            payload = {'pet_id': pets[owner][pet]['id'], 'service_id': services[service]['id']}
            if service < 3:
                payload['grooming_start'] = instant or scheduled(day, hour)
            else:
                payload.update(boarding_start=(anchor + timedelta(days=day)).isoformat(), boarding_end=(anchor + timedelta(days=day + stay)).isoformat())
            b = call('POST', '/bookings', payload, owners[owner])
            story.append({'story': label, 'booking_id': b['id'], 'owner': CUSTOMERS[owner][1], 'pet': pets[owner][pet]['name'], 'booking_type': b['booking_type']})
            return b
        def assign(b, index):
            return call('PUT', f"/admin/bookings/{b['id']}/staff", {'staff_user_id': staff[index]['id']}, admin)
        def decide(b, status='CONFIRMED'):
            return call('POST', f"/admin/bookings/{b['id']}/status", {'status': status}, admin)
        def allocate(b, index):
            return call('PUT', f"/admin/bookings/{b['id']}/accommodation", {'accommodation_id': units[index]['id']}, admin)
        # Both appointments genuinely reach their scheduled time before Staff act.
        appointment = datetime.now(zone) + timedelta(seconds=10)
        early = [create('Completed Grooming', 0, 0, 0, instant=appointment.isoformat()),
                 create('Completed Grooming', 1, 0, 1, instant=appointment.isoformat())]
        for i, b in enumerate(early): assign(b, i); decide(b)
        while datetime.now(zone) < appointment: clock.sleep(.2)
        for i, b in enumerate(early):
            call('POST', f"/grooming/bookings/{b['id']}/start", {}, staff_tokens[i])
            call('POST', f"/grooming/bookings/{b['id']}/complete", {'service_notes': 'Coat brushed and dried; grooming completed.'}, staff_tokens[i])
        b = create('Completed Boarding walkthrough', 2, 1, 3, stay=1); allocate(b, 1); assign(b, 2); decide(b)
        call('POST', f"/boarding/bookings/{b['id']}/check-in", {}, admin)
        call('POST', f"/boarding/bookings/{b['id']}/notes", {'note': 'Settled comfortably; water refreshed before collection.'}, staff_tokens[2])
        call('POST', f"/boarding/bookings/{b['id']}/check-out", {}, admin)
        for owner, pet, duration, member in [(0, 1, 2, 0), (3, 0, 1, 1)]:
            b = create('Current Boarding stay', owner, pet, 3, stay=duration); allocate(b, 0); assign(b, member); decide(b)
            call('POST', f"/boarding/bookings/{b['id']}/check-in", {}, admin)
            call('POST', f"/boarding/bookings/{b['id']}/notes", {'note': 'Resting comfortably; water refreshed.'}, staff_tokens[member])
        for owner, pet, service, day, hour, member in [(0, 0, 0, 2, 10, 2), (1, 1, 1, 3, 11, 1)]:
            b = create('Upcoming confirmed Grooming', owner, pet, service, day, hour); assign(b, member); decide(b)
        create('Grooming awaiting review', 3, 1, 2, 1, 14)
        create('Grooming awaiting review', 2, 0, 0, 4, 10)
        for owner, pet, day, stay, unit, member in [(1, 0, 3, 2, 1, 0), (2, 1, 6, 2, 0, 2)]:
            b = create('Upcoming confirmed Boarding', owner, pet, 3, day, stay=stay); allocate(b, unit); assign(b, member); decide(b)
        create('Boarding awaiting review', 0, 0, 3, 5)
        b = create('Cancelled confirmed Grooming', 0, 0, 0, 5); assign(b, 2); decide(b)
        call('POST', f"/bookings/{b['id']}/cancel", {}, owners[0])
        b = create('Cancelled confirmed Boarding', 1, 1, 3, 4); allocate(b, 0); assign(b, 1); decide(b)
        call('POST', f"/bookings/{b['id']}/cancel", {}, owners[1])
        b = create('Rescheduled and reconfirmed Grooming', 0, 0, 1, 7); assign(b, 1); decide(b)
        call('POST', f"/bookings/{b['id']}/reschedule", {'grooming_start': scheduled(8, 14)}, owners[0]); assign(b, 2); decide(b)
        b = create('Rescheduled Boarding awaiting review', 3, 1, 3, 8)
        call('POST', f"/bookings/{b['id']}/reschedule", {'boarding_start': (anchor + timedelta(days=9)).isoformat(), 'boarding_end': (anchor + timedelta(days=11)).isoformat()}, owners[3])
        b = create('Rejected Grooming request', 2, 0, 2, 5, 15); decide(b, 'REJECTED')
        actual = {b['id']: b for kind in ['grooming', 'boarding'] for b in call('GET', '/' + kind + '/bookings', token=admin)}
        for row in story: row['final_status'] = actual[row['booking_id']]['status']
        for token in [admin, *staff_tokens, *owners]: call('POST', '/auth/logout', {}, token)
    engine.dispose()
    return {**plan(anchor), 'records': story, 'mechanism': 'Admin bootstrap only; all business records/actions via existing API handlers; actual timestamps; no status/history/time SQL'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--anchor-date', type=date.fromisoformat, required=True)
    p.add_argument('--apply', action='store_true'); p.add_argument('--reset', action='store_true')
    p.add_argument('--evidence', type=Path)
    args = p.parse_args()
    if not args.apply:
        print(json.dumps(plan(args.anchor_date), indent=2)); return
    raw = os.environ.get('PETOPS_FINAL_DEMO_DATABASE_URL', '')
    if not raw: p.error('Set PETOPS_FINAL_DEMO_DATABASE_URL privately; no default target')
    try:
        result = apply(raw, args.anchor_date, args.reset)
    except Exception as exc:
        raise SystemExit(str(exc) if isinstance(exc, DemoStepError) else f'Demo stopped ({type(exc).__name__}); target retained for local inspection. No UAT database selected.') from None
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'fixture': MARKER, 'database': DATABASE, 'records': len(result['records']), 'fictional_only': True}))


if __name__ == '__main__': main()
