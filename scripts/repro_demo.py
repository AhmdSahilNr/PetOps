"""Opt-in fictional fixture for ONE dedicated local developer database, never UAT."""
import argparse
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy.engine import make_url

DATABASE = 'petops_repro_demo_test'
MARKER = 'petops-fictional-repro-v1'
ADMIN_ID = UUID('e75c192b-3ac1-56ee-9fe5-f4caa3909023')
EMAILS = {f'{role}.repro@petops.example' for role in ('admin', 'staff', 'customer')}
PASSWORD = 'DemoPass!123'  # Public fictional fixture only, not a production credential.
class FixtureStepError(RuntimeError): pass

def validate_target(raw):
    u = make_url(raw)
    if u.drivername != 'postgresql+psycopg' or u.host not in {'127.0.0.1', 'localhost'} or u.database != DATABASE or u.query:
        raise ValueError('Only plain loopback postgresql+psycopg URLs for petops_repro_demo_test are permitted')
    return u

def plan(anchor):
    return {'fixture': MARKER, 'database': DATABASE, 'anchor_date_myt': anchor.isoformat(),
            'accounts': sorted(EMAILS), 'services': ['Basic Grooming', 'Premium Grooming', 'Standard Boarding'],
            'pets': ['Fictional Oyen', 'Fictional Pip', 'Fictional Mochi'],
            'bookings': ['Requested Grooming: anchor+1 at10MYT', 'Confirmed Grooming: anchor+2 at11MYT', 'Confirmed Boarding: anchor+3 through anchor+5'],
            'limits': 'Semantic state/dates/order are repeatable for an anchor; generated IDs, password hashes, event/session timestamps differ. No completed-care facts fabricated.'}

def apply(raw, anchor, reset=False):
    validate_target(raw)
    zone = ZoneInfo('Asia/Kuala_Lumpur')
    if anchor < datetime.now(zone).date(): raise ValueError('Anchor must not be in the past')
    os.environ['PETOPS_DATABASE_URL'] = raw
    os.environ['PETOPS_REMINDER_POLL_SECONDS'] = '0'
    from sqlalchemy import create_engine, text, select
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parents[1]
    from app.database import SessionLocal, reset_database_caches
    reset_database_caches()
    engine = create_engine(raw)
    with engine.connect() as db:
        actual, address = db.execute(text('SELECT current_database(),host(inet_server_addr())')).one()
        if actual != DATABASE or address not in {'127.0.0.1', '::1'}: raise ValueError('Resolved target is not the dedicated loopback database')
        marker = db.execute(text('SELECT shobj_description(oid,\'pg_database\') FROM pg_database WHERE datname=current_database()')).scalar_one()
        existing = db.execute(text("SELECT to_regclass('public.users')")).scalar_one()
        if existing:
            users = db.execute(text('SELECT id,email FROM users')).all()
            if users and not reset: raise ValueError('Fixture exists; no records changed. Reset requires --reset --apply')
            if reset and (marker != MARKER or not users or not set(e for _, e in users) <= EMAILS or (ADMIN_ID, 'admin.repro@petops.example') not in users):
                raise ValueError('Reset refused: marker or exact fictional account ownership differs')
        elif reset: raise ValueError('Reset refused: no managed fixture exists')
        if marker not in (None, MARKER): raise ValueError('Database has a different ownership marker')
    cfg = Config(str(root / 'alembic.ini')); cfg.set_main_option('script_location', str(root / 'alembic'))
    command.upgrade(cfg, 'head')
    with engine.begin() as db:
        if db.execute(text('SELECT version_num FROM alembic_version')).scalar_one() != '0008': raise ValueError('Review fixture for the new migration head first')
        db.execute(text("COMMENT ON DATABASE petops_repro_demo_test IS 'petops-fictional-repro-v1'"))
        if reset:
            # Only a verified fixture-owned developer database; never main/demo/UAT.
            db.execute(text('TRUNCATE staff_responsibilities,management_events,notifications,notification_settings,boarding_notes,boarding_stays,grooming_records,boarding_allocations,booking_events,bookings,staff_availability,accommodations,services,pets,customers,user_sessions,users'))
            db.execute(text('INSERT INTO notification_settings(id,enabled) VALUES (1,false)'))
    from app.models import User, Role
    from app.security import hash_password
    with SessionLocal() as db:
        db.add(User(id=ADMIN_ID,email='admin.repro@petops.example',password_hash=hash_password(PASSWORD),role=Role.ADMIN,display_name='Fictional Admin'))
        db.commit()
    # The bootstrap Admin is fixture infrastructure. All business setup uses
    # the same application handlers/guards as a normal Customer/Admin request.
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        def call(method, path, body=None, token=None):
            response = client.request(method, path, json=body, headers={'Authorization': 'Bearer '+token} if token else {})
            if response.status_code not in {200,201,204}: raise FixtureStepError(f'Fixture API step refused ({response.status_code}) at {method} {path}; partial fixture retained')
            return None if response.status_code==204 else response.json()
        admin = call('POST','/auth/login',{'email':'admin.repro@petops.example','password':PASSWORD})['token']
        staff = call('POST','/admin/staff',{'email':'staff.repro@petops.example','password':PASSWORD,'display_name':'Fictional Staff'},admin)
        services = []
        for name, kind, duration, order in [('Basic Grooming','GROOMING',30,10),('Premium Grooming','GROOMING',60,20),('Standard Boarding','BOARDING',None,10)]:
            services.append(call('POST','/admin/services',{'name':name,'service_type':kind,'duration_minutes':duration,'display_order':order},admin))
        unit = call('POST','/admin/accommodations',{'name':'Fictional Garden Unit','category':'Fictional','capacity':3,'is_active':True},admin)
        call('POST','/auth/register',{'email':'customer.repro@petops.example','password':PASSWORD,'display_name':'Fictional Customer'})
        owner = call('POST','/auth/login',{'email':'customer.repro@petops.example','password':PASSWORD})['token']
        pets = [call('POST','/pets',{'name':name},owner) for name in plan(anchor)['pets']]
        for index in range(3):
            payload={'pet_id':pets[index]['id'],'service_id':services[index]['id']}
            if index<2: payload['grooming_start']=datetime.combine(anchor+timedelta(days=index+1),time(10+index),zone).isoformat()
            else: payload.update(boarding_start=(anchor+timedelta(days=3)).isoformat(),boarding_end=(anchor+timedelta(days=5)).isoformat())
            booking=call('POST','/bookings',payload,owner)
            if index==0: continue
            if index==2: call('PUT',f"/admin/bookings/{booking['id']}/accommodation",{'accommodation_id':unit['id']},admin)
            call('PUT',f"/admin/bookings/{booking['id']}/staff",{'staff_user_id':staff['id']},admin)
            call('POST',f"/admin/bookings/{booking['id']}/status",{'status':'CONFIRMED'},admin)
        for token in (admin,owner): call('POST','/auth/logout',{},token)
    engine.dispose()
    return plan(anchor)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--anchor-date',type=date.fromisoformat,required=True);p.add_argument('--apply',action='store_true');p.add_argument('--reset',action='store_true');args=p.parse_args()
    if not args.apply:
        print(json.dumps(plan(args.anchor_date),indent=2));return
    raw=os.environ.get('PETOPS_REPRO_DATABASE_URL','')
    if not raw: p.error('Set PETOPS_REPRO_DATABASE_URL privately; no default connection is used')
    try: result=apply(raw,args.anchor_date,args.reset)
    except Exception as exc:
        # Drivers can include credentials in exception details. Never print them.
        raise SystemExit(str(exc) if isinstance(exc,FixtureStepError) else f'Fixture stopped ({type(exc).__name__}); inspect the dedicated developer database locally. No UAT target was selected.') from None
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
