"""Reproducible local PG evidence. No connection URLs/passwords are logged.

prepare creates isolated databases; other commands refuse destructive resets.
--prefix frozen selects fresh commit-bound proof databases after code freeze.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, make_url, text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs/evidence/slice2'
CONFIG = ROOT/'.local/slice2-config.json'
PROTECTED = ('app','alembic','scripts','tests','requirements.txt','requirements.lock.txt','alembic.ini','.gitignore','.gitattributes','.env.example')


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT).decode().strip()


def fingerprint():
    result={}
    for name in PROTECTED:
        p=ROOT/name
        for f in (sorted(p.rglob('*')) if p.is_dir() else [p]):
            if f.is_file() and '__pycache__' not in f.parts:
                result[f.relative_to(ROOT).as_posix()]=hashlib.sha256(f.read_bytes()).hexdigest()
    return result


def matches_commit(commit,files):
    for name,digest in files.items():
        r=subprocess.run(['git','show',commit+':'+name],cwd=ROOT,capture_output=True)
        if r.returncode or hashlib.sha256(r.stdout).hexdigest()!=digest: return False
    return True


def prepare():
    if CONFIG.exists():
        print('Slice 2 database config exists; no database reset performed.')
        return
    original=json.loads((ROOT/'.local/postgres-config.json').read_text())
    template=make_url(original['test_url'])
    assert template.host=='127.0.0.1' and template.port==55432
    names={'test_url':'petops_slice2_test','upgrade_url':'petops_slice2_upgrade_test',
           'frozen_test_url':'petops_slice2_frozen_test','frozen_upgrade_url':'petops_slice2_frozen_upgrade_test',
           'migration_url':'petops_slice2_runtime'}
    with psycopg.connect(host='127.0.0.1',port=55432,user='petops_local_admin',
        password=(ROOT/'.local/pgpassword').read_text().strip(),dbname='postgres',autocommit=True) as conn:
        for dbname in names.values():
            if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(dbname,)).fetchone():
                raise RuntimeError('Dedicated database already exists; explicit review required, never reset automatically')
            conn.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(dbname),sql.Identifier(template.username)))
    config={key:template.set(database=name).render_as_string(hide_password=False) for key,name in names.items()}
    config['runtime_url']=make_url(original['runtime_url']).set(database=names['migration_url']).render_as_string(hide_password=False)
    CONFIG.write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('Created isolated Slice 2 test/upgrade/runtime databases; credentials remain in ignored local config.')


def run(args,url,filename):
    with (OUT/filename).open('w',encoding='utf-8') as stream:
        result=subprocess.run([sys.executable,*args],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':url,'PETOPS_TEST_DATABASE_URL':url},stdout=stream,stderr=subprocess.STDOUT)
    print(filename+': exit '+str(result.returncode),flush=True)
    if result.returncode: raise RuntimeError('See docs/evidence/slice2/'+filename)


def empty(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one()==0


def clean(config,prefix):
    url=config['frozen_test_url' if prefix=='frozen' else 'test_url']; engine=create_engine(url)
    assert empty(engine),'Clean-migration database must be empty; no reset performed'
    run(['-m','alembic','upgrade','head'],url,prefix+'-clean-migration.txt')
    run(['-m','alembic','upgrade','head'],url,prefix+'-repeat-migration.txt')
    run(['-m','alembic','check'],url,prefix+'-schema-check.txt')
    engine.dispose()
    return {'empty_database_observed':True,'revision':'0003','repeat_upgrade_and_schema_check':'PASS'}


def upgrade(config,prefix):
    from app.security import hash_password
    url=config['frozen_upgrade_url' if prefix=='frozen' else 'upgrade_url']; engine=create_engine(url)
    assert empty(engine),'Populated-upgrade database must start empty; no reset performed'
    run(['-m','alembic','upgrade','0002'],url,prefix+'-legacy-schema.txt')
    ids={k:uuid.uuid4() for k in ('user','customer','pet','service','booking','event')}; now=datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(text("INSERT INTO users(id,email,password_hash,role,is_active,created_at) VALUES (:user,'slice2.upgrade@petops.example',:password,'CUSTOMER',true,:now)"),{**ids,'password':hash_password('FictionalPass!123'),'now':now})
        c.execute(text("INSERT INTO customers(id,user_id,display_name,created_at,updated_at) VALUES (:customer,:user,'Upgrade Demo',:now,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO pets(id,customer_id,name,created_at,updated_at) VALUES (:pet,:customer,'Upgrade Pet',:now,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO services(id,name,service_type,is_active,created_at) VALUES (:service,'Unconfigured Legacy Grooming','GROOMING',true,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO bookings(id,customer_id,pet_id,service_id,booking_type,status,grooming_start,created_by_user_id,created_at,updated_at) VALUES (:booking,:customer,:pet,:service,'GROOMING','SUBMITTED',:start,:user,:now,:now)"),{**ids,'start':now+timedelta(days=3),'now':now})
        c.execute(text("INSERT INTO booking_events(id,booking_id,event_type,new_status,actor_user_id,created_at) VALUES (:event,:booking,'BOOKING_SUBMITTED','SUBMITTED',:user,:now)"),{**ids,'now':now})
    run(['-m','alembic','upgrade','head'],url,prefix+'-populated-upgrade.txt')
    with engine.connect() as c:
        row=c.execute(text('SELECT id,customer_id,pet_id,service_id,grooming_duration_minutes FROM bookings')).one()
        assert tuple(row)==(ids['booking'],ids['customer'],ids['pet'],ids['service'],None)
        event=c.execute(text('SELECT id,actor_user_id,created_at FROM booking_events')).one()
        assert tuple(event)==(ids['event'],ids['user'],now)
        assert c.execute(text('SELECT duration_minutes FROM services')).scalar_one() is None
    from sqlalchemy.exc import IntegrityError
    denied=False
    try:
        with engine.begin() as c: c.execute(text("UPDATE bookings SET status='CONFIRMED' WHERE id=:id"),{'id':ids['booking']})
    except IntegrityError: denied=True
    assert denied,'Legacy request must not confirm without configuration/assignment'
    engine.dispose()
    return {'populated_0002_to_0003':'PASS','ids_links_actor_timestamp_preserved':True,
            'unknown_duration_not_invented':True,'legacy_confirmation_denied':True}


def runtime(config,prefix):
    migration=config['migration_url']; url=config['runtime_url']; engine=create_engine(migration)
    if empty(engine):
        run(['-m','alembic','upgrade','head'],migration,prefix+'-runtime-migration.txt')
        run(['-m','scripts.seed_demo'],migration,prefix+'-seed.txt')
    with engine.begin() as c:
        c.execute(text('GRANT USAGE ON SCHEMA public TO petops_runtime'))
        c.execute(text('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM petops_runtime'))
        c.execute(text('GRANT SELECT,INSERT ON users,user_sessions,customers,pets,bookings,booking_events,staff_availability,accommodations,boarding_allocations TO petops_runtime'))
        c.execute(text('GRANT UPDATE ON customers,pets,bookings,staff_availability,accommodations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (scheduling_version) ON users TO petops_runtime'))
        c.execute(text('GRANT SELECT ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (duration_minutes,updated_by_user_id,updated_at) ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (released_at,released_by_user_id) ON boarding_allocations TO petops_runtime'))
        c.execute(text('GRANT DELETE ON pets TO petops_runtime'))
        staff=c.execute(text("SELECT id FROM users WHERE email='staff.demo@petops.example'")).scalar_one()
        unit=c.execute(text("SELECT id FROM accommodations WHERE name='Fictional Demo Unit'")).scalar_one()
    base='http://127.0.0.1:58080'
    def start(label):
        stream=(OUT/(prefix+'-http-'+label+'.txt')).open('w',encoding='utf-8')
        p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','58080'],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':url,'PETOPS_ENV':'development'},stdout=stream,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(100):
            try:
                if httpx.get(base+'/health',timeout=1).status_code==200: return p,stream
            except httpx.HTTPError: pass
            if p.poll() is not None: raise RuntimeError('Runtime server exited; inspect HTTP log')
            time.sleep(.2)
        p.terminate(); p.wait(timeout=10); stream.close(); raise RuntimeError('Readiness timeout')
    def stop(p,stream): p.terminate(); p.wait(timeout=10); stream.close()
    def expect(r,status):
        assert r.status_code==status,(r.status_code,r.text)
        return r.json()
    p,stream=start('first'); saved=[]
    try:
        with httpx.Client(base_url=base) as c:
            email=f'slice2.runtime.{uuid.uuid4().hex[:10]}@petops.example'
            owner=expect(c.post('/auth/register',json={'email':email,'password':'FictionalPass!123','display_name':'Slice 2 Runtime Demo'}),201)
            token=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}),200)['token']
            own={'Authorization':'Bearer '+token}
            administrator=expect(c.post('/auth/login',json={'email':'admin.demo@petops.example','password':'DemoPass!123'}),200)
            admin={'Authorization':'Bearer '+administrator['token']}
            pet=expect(c.post('/pets',headers=own,json={'name':'Fictional Slice 2 Pet'}),201)
            services=expect(c.get('/services',headers=own),200)
            for kind in ('GROOMING','BOARDING'):
                service=next(s for s in services if s['service_type']==kind)
                now=datetime.now(timezone.utc)
                schedule={'grooming_start':(now+timedelta(days=2)).isoformat()} if kind=='GROOMING' else {
                    'boarding_start':(now+timedelta(days=2)).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat(),
                    'boarding_end':(now+timedelta(days=4)).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kuala_Lumpur')).date().isoformat()}
                b=expect(c.post('/bookings',headers=own,json={'pet_id':pet['id'],'service_id':service['id'],**schedule}),201); bid=b['id']
                expect(c.post(f'/admin/bookings/{bid}/status',headers=admin,json={'status':'CONFIRMED'}),409)
                def reserve():
                    path='staff' if kind=='GROOMING' else 'accommodation'
                    body={'staff_user_id':str(staff)} if kind=='GROOMING' else {'accommodation_id':str(unit)}
                    expect(c.put(f'/admin/bookings/{bid}/{path}',headers=admin,json=body),200)
                reserve(); expect(c.post(f'/admin/bookings/{bid}/status',headers=admin,json={'status':'CONFIRMED'}),200)
                changed={'grooming_start':(now+timedelta(days=5)).isoformat()} if kind=='GROOMING' else {
                    'boarding_start':(now+timedelta(days=5)).date().isoformat(),'boarding_end':(now+timedelta(days=7)).date().isoformat()}
                expect(c.post(f'/bookings/{bid}/reschedule',headers=own,json=changed),200)
                expect(c.post(f'/admin/bookings/{bid}/status',headers=admin,json={'status':'CONFIRMED'}),409)
                reserve(); expect(c.post(f'/admin/bookings/{bid}/status',headers=admin,json={'status':'CONFIRMED'}),200)
                expect(c.post(f'/bookings/{bid}/cancel',headers=own),200)
                h=expect(c.get(f'/bookings/{bid}/history',headers=own),200)
                assert len(h)==7 and all(e['actor_user_id'] in {owner['id'],administrator['user']['id']} and datetime.fromisoformat(e['created_at']).tzinfo for e in h)
                saved.append((bid,h))
    finally: stop(p,stream)
    p,stream=start('restarted')
    try:
        with httpx.Client(base_url=base) as c:
            token=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}),200)['token']; own={'Authorization':'Bearer '+token}
            for bid,h in saved:
                assert expect(c.get(f'/bookings/{bid}',headers=own),200)['status']=='CANCELLED'
                assert expect(c.get(f'/bookings/{bid}/history',headers=own),200)==h
    finally: stop(p,stream)
    with create_engine(url).connect() as c:
        assert not c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")).scalar_one()
        for table in ('booking_events','boarding_allocations','bookings'):
            assert not c.execute(text("SELECT has_table_privilege(current_user,:t,'DELETE')"),{'t':table}).scalar_one()
        assert not c.execute(text("SELECT has_column_privilege(current_user,'users','role','UPDATE')")).scalar_one()
        assert c.execute(text("SELECT has_column_privilege(current_user,'users','scheduling_version','UPDATE')")).scalar_one()
    engine.dispose()
    return {'real_http_server_processes':2,'both_booking_types_confirmed_rescheduled_reconfirmed_cancelled':True,
        'missing_prerequisites_denied_before_and_after_reschedule':True,'identical_history_after_restart':True,
        'events_per_booking':7,'actor_and_timezone_verified':True,'non_superuser_runtime_and_restricted_privileges':True}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['prepare','clean','upgrade','runtime','test'])
    parser.add_argument('--prefix',choices=['dev','frozen'],default='dev'); args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.command=='prepare': prepare(); return
    config=json.loads(CONFIG.read_text()); before=fingerprint(); commit=git('rev-parse','HEAD')
    bound=matches_commit(commit,before); started=datetime.now(timezone.utc).isoformat(); prefix=args.prefix
    if args.command=='test':
        url=config['frozen_test_url' if prefix=='frozen' else 'test_url']
        run(['-m','pytest','-q','--tb=short'],url,prefix+'-tests.txt')
        log=(OUT/(prefix+'-tests.txt')).read_text()
        result={'pytest_summary':next(l for l in reversed(log.splitlines()) if 'passed' in l),'exit_code':0,
                'command':[sys.executable,'-m','pytest','-q','--tb=short']}
    else: result=globals()[args.command](config,prefix)
    assert fingerprint()==before,'Source changed during verification'
    record={'command':args.command,'prefix':prefix,'commit':commit,'tree':git('rev-parse',commit+'^{tree}'),
        'source_matches_commit_before_and_after':bound and matches_commit(commit,before),
        'source_sha256':before,'started_at_utc':started,'finished_at_utc':datetime.now(timezone.utc).isoformat(),
        'result':result,'credentials_logged':False}
    (OUT/(prefix+'-'+args.command+'-record.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
