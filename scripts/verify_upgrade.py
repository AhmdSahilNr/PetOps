"""Prove 0001 -> 0002 preserves existing fictional records, on dedicated PG DB."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from sqlalchemy import create_engine, text
from app.security import hash_password

ROOT = Path(__file__).resolve().parents[1]


def main():
    url = json.loads((ROOT/'.local/postgres-config.json').read_text())['upgrade_url']
    engine = create_engine(url)
    env = {**os.environ,'PETOPS_DATABASE_URL':url}
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one()==0, 'Dedicated upgrade DB must be empty'
    subprocess.run([sys.executable,'-m','alembic','upgrade','0001'],env=env,check=True)
    ids = {k:uuid.uuid4() for k in ('user','staff','customer','pet','service','booking','event')}
    now = datetime.now(timezone.utc)
    start = now+timedelta(days=2)
    schedule = json.dumps({'grooming_start':start.isoformat(),'boarding_start':None,'boarding_end':None})
    with engine.begin() as c:
        for key,role in [('user','CUSTOMER'),('staff','STAFF')]:
            c.execute(text('INSERT INTO users(id,email,password_hash,role,is_active,created_at) VALUES (:id,:email,:password,:role,true,:now)'),{'id':ids[key],'email':f'upgrade.{key}@petops.example','password':hash_password('FictionalPass!123'),'role':role,'now':now})
        c.execute(text('INSERT INTO customers(id,user_id,display_name,created_at,updated_at) VALUES (:customer,:user,\'Upgrade Demo\',:now,:now)'),{**ids,'now':now})
        c.execute(text('INSERT INTO pets(id,customer_id,name,created_at,updated_at) VALUES (:pet,:customer,\'Upgrade Demo Pet\',:now,:now)'),{**ids,'now':now})
        c.execute(text("INSERT INTO services(id,name,service_type,is_active,created_at) VALUES (:service,'Upgrade Grooming','GROOMING',true,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO bookings(id,customer_id,pet_id,service_id,booking_type,status,grooming_start,assigned_staff_user_id,created_by_user_id,created_at,updated_at) VALUES (:booking,:customer,:pet,:service,'GROOMING','SUBMITTED',:start,:staff,:user,:now,:now)"),{**ids,'start':start,'now':now})
        c.execute(text("INSERT INTO booking_events(id,booking_id,event_type,new_status,new_schedule,actor_user_id,created_at) VALUES (:event,:booking,'BOOKING_SUBMITTED','SUBMITTED',CAST(:schedule AS json),:user,:now)"),{**ids,'schedule':schedule,'now':now})
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,check=True)
    with engine.connect() as c:
        booking = c.execute(text('SELECT id,customer_id,pet_id,service_id,grooming_start,assigned_staff_user_id,version FROM bookings')).one()
        assert tuple(booking)==(ids['booking'],ids['customer'],ids['pet'],ids['service'],start,ids['staff'],1)
        event = c.execute(text('SELECT id,actor_user_id,created_at,new_schedule FROM booking_events')).one()
        assert tuple(event)==(ids['event'],ids['user'],now,json.loads(schedule))
        assert c.execute(text("SELECT account_role FROM customers")).scalar_one()=='CUSTOMER'
    print('PASS: populated 0001 -> 0002 retained UUIDs, Customer/Pet/Service links, schedule, Staff assignment, actor, timestamp and original event JSON; version initialized to 1.')
    engine.dispose()


if __name__ == '__main__':
    main()
