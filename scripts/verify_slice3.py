"""Local commit-bound PostgreSQL evidence. Credentials stay in ignored .local.

prepare creates new dedicated databases, never resets an existing database.
The test command clears only the dedicated loopback *_test database entity rows.
"""
import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import httpx
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from scripts.verify_slice2 import fingerprint, git, matches_commit

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/slice3'
CONFIG=ROOT/'.local/slice3-config.json'


def prepare():
    if CONFIG.exists():
        print('Slice 3 private config already exists; no databases changed.');return
    old=json.loads((ROOT/'.local/postgres-config.json').read_text())
    template=make_url(old['test_url'])
    assert template.host=='127.0.0.1' and template.port==55432
    names={key:'petops_slice3_'+value for key,value in {
        'test_url':'dev_test','upgrade_url':'dev_upgrade_test','migration_url':'runtime',
        'frozen_test_url':'frozen_test','frozen_upgrade_url':'frozen_upgrade_test'}.items()}
    with psycopg.connect(host=template.host,port=template.port,user='petops_local_admin',
        password=(ROOT/'.local/pgpassword').read_text().strip(),dbname='postgres',autocommit=True) as conn:
        for name in names.values():
            assert conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone() is None,'Dedicated DB exists; no reset allowed'
        for name in names.values():
            conn.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name),sql.Identifier(template.username)))
    config={key:template.set(database=name).render_as_string(hide_password=False) for key,name in names.items()}
    config['runtime_url']=make_url(old['runtime_url']).set(database=names['migration_url']).render_as_string(hide_password=False)
    CONFIG.write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('Created isolated Slice 3 databases; private credentials excluded from evidence.')


def run(args,url,filename,allow_failure=False):
    with (OUT/filename).open('w',encoding='utf-8') as f:
        p=subprocess.run([sys.executable,*args],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':url,'PETOPS_TEST_DATABASE_URL':url},stdout=f,stderr=subprocess.STDOUT)
    print(filename+': exit '+str(p.returncode),flush=True)
    if not allow_failure and p.returncode: raise RuntimeError('Verification command failed; inspect retained log')
    return p.returncode


def empty(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public'")).scalar_one()==0


def clean(config,prefix):
    url=config['frozen_test_url' if prefix=='frozen' else 'test_url'];engine=create_engine(url)
    assert empty(engine),'Clean proof requires empty DB; no reset performed'
    for args,name in [(['upgrade','head'],'clean-migration'),(['upgrade','head'],'repeat-migration'),(['check'],'schema-check')]:
        run(['-m','alembic',*args],url,prefix+'-'+name+'.txt')
    with engine.connect() as c: assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0004'
    engine.dispose();return {'empty_database_observed':True,'revision':'0004','repeat_and_model_agreement':'PASS'}


def upgrade(config,prefix):
    url=config['frozen_upgrade_url' if prefix=='frozen' else 'upgrade_url'];engine=create_engine(url)
    assert empty(engine),'Upgrade proof requires empty DB; no reset performed'
    run(['-m','alembic','upgrade','0003'],url,prefix+'-legacy-schema.txt')
    ids={k:uuid.uuid4() for k in ('user','customer','pet','service','booking','event')};now=datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(text("INSERT INTO users(id,email,password_hash,role,is_active,created_at) VALUES (:user,'slice3.upgrade@petops.example','not-a-login-hash','CUSTOMER',true,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO customers(id,user_id,display_name,created_at,updated_at) VALUES (:customer,:user,'Fictional Upgrade Customer',:now,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO pets(id,customer_id,name,created_at,updated_at) VALUES (:pet,:customer,'Fictional Upgrade Pet',:now,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO services(id,name,service_type,is_active,created_at,duration_minutes) VALUES (:service,'Fictional Grooming','GROOMING',true,:now,60)"),{**ids,'now':now})
        c.execute(text("INSERT INTO bookings(id,customer_id,pet_id,service_id,booking_type,status,grooming_start,grooming_duration_minutes,created_by_user_id,created_at,updated_at) VALUES (:booking,:customer,:pet,:service,'GROOMING','SUBMITTED',:start,60,:user,:now,:now)"),{**ids,'start':now+timedelta(days=3),'now':now})
        c.execute(text("INSERT INTO booking_events(id,booking_id,event_type,new_status,actor_user_id,created_at) VALUES (:event,:booking,'BOOKING_SUBMITTED','SUBMITTED',:user,:now)"),{**ids,'now':now})
        # Intentionally malformed pre-0004 fixture, solely to prove migration preflight.
        c.execute(text("UPDATE bookings SET status='IN_PROGRESS' WHERE id=:booking"),ids)
    code=run(['-m','alembic','upgrade','head'],url,prefix+'-legacy-anomaly-denied.txt',allow_failure=True)
    assert code!=0
    with engine.begin() as c:
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0003'
        assert c.execute(text("SELECT to_regclass('public.grooming_records')")).scalar_one() is None
        # Restore the deliberately introduced fixture to its known original state.
        c.execute(text("UPDATE bookings SET status='SUBMITTED' WHERE id=:booking"),ids)
    run(['-m','alembic','upgrade','head'],url,prefix+'-populated-upgrade.txt')
    with engine.connect() as c:
        assert tuple(c.execute(text('SELECT id,customer_id,pet_id,service_id FROM bookings')).one())==(ids['booking'],ids['customer'],ids['pet'],ids['service'])
        assert tuple(c.execute(text('SELECT id,actor_user_id,created_at FROM booking_events')).one())==(ids['event'],ids['user'],now)
        assert c.execute(text('SELECT count(*) FROM grooming_records')).scalar_one()==0
    engine.dispose();return {'populated_0003_to_0004':'PASS','links_actor_timestamp_preserved':True,
        'legacy_anomaly_denied_and_migration_rolled_back':True,'no_operational_history_fabricated':True}


def runtime(config,prefix):
    migration=config['migration_url'];url=config['runtime_url'];engine=create_engine(migration)
    run(['-m','alembic','upgrade','head'],migration,prefix+'-runtime-migration.txt')
    run(['-m','scripts.seed_demo'],migration,prefix+'-seed.txt')
    with engine.begin() as c:
        c.execute(text('GRANT USAGE ON SCHEMA public TO petops_runtime'))
        c.execute(text('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM petops_runtime'))
        c.execute(text('GRANT SELECT,INSERT ON users,user_sessions,customers,pets,bookings,booking_events,staff_availability,accommodations,boarding_allocations,grooming_records TO petops_runtime'))
        c.execute(text('GRANT UPDATE ON customers,pets,bookings,staff_availability,accommodations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (scheduling_version) ON users TO petops_runtime'))
        c.execute(text('GRANT SELECT ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (duration_minutes,updated_by_user_id,updated_at) ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (released_at,released_by_user_id) ON boarding_allocations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (completed_at,completed_by_user_id,service_notes) ON grooming_records TO petops_runtime'))
        c.execute(text('GRANT DELETE ON pets,user_sessions TO petops_runtime'))
        staff=str(c.execute(text("SELECT id FROM users WHERE email='staff.demo@petops.example'")).scalar_one())
    base='http://127.0.0.1:58081'
    def start(label):
        try:
            httpx.get(base+'/health',timeout=1)
        except httpx.HTTPError: pass
        else: raise RuntimeError('Proof port already occupied; no existing process stopped')
        stream=(OUT/(prefix+'-http-'+label+'.txt')).open('w',encoding='utf-8')
        p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','58081'],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':url,'PETOPS_ENV':'development'},stdout=stream,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(100):
            try:
                if httpx.get(base+'/health',timeout=1).status_code==200:return p,stream
            except httpx.HTTPError:pass
            if p.poll() is not None:break
            time.sleep(.2)
        p.terminate();p.wait(timeout=10);stream.close();raise RuntimeError('HTTP readiness failed')
    def stop(p,f):p.terminate();p.wait(timeout=10);f.close()
    def expect(r,status=200):
        assert r.status_code==status,(r.status_code,r.text)
        return r.json() if status!=204 else None
    email='slice3.runtime.'+uuid.uuid4().hex[:12]+'@petops.example'
    p,f=start('first')
    try:
        with httpx.Client(base_url=base) as c:
            assert c.get('/').status_code==c.get('/static/demo.js').status_code==200
            expect(c.post('/auth/register',json={'email':email,'password':'FictionalPass!123','display_name':'Fictional Grooming Customer'}),201)
            owner=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}))
            own={'Authorization':'Bearer '+owner['token']}
            pet=expect(c.post('/pets',headers=own,json={'name':'Fictional Grooming Pet'}),201)
            service=next(s for s in expect(c.get('/services',headers=own)) if s['service_type']=='GROOMING')
            schedule={'service_id':service['id'],'grooming_start':(datetime.now(timezone.utc)+timedelta(days=2,seconds=uuid.uuid4().int%60000)).isoformat()}
            assert expect(c.post('/availability',headers=own,json=schedule))['available']
            b=expect(c.post('/bookings',headers=own,json={'pet_id':pet['id'],**schedule}),201);bid=b['id']
            admin=expect(c.post('/auth/login',json={'email':'admin.demo@petops.example','password':'DemoPass!123'}));ah={'Authorization':'Bearer '+admin['token']}
            expect(c.post(f'/admin/bookings/{bid}/status',headers=ah,json={'status':'CONFIRMED'}),409)
            expect(c.put(f'/admin/bookings/{bid}/staff',headers=ah,json={'staff_user_id':staff}))
            expect(c.post(f'/admin/bookings/{bid}/status',headers=ah,json={'status':'CONFIRMED'}))
            staff_login=expect(c.post('/auth/login',json={'email':'staff.demo@petops.example','password':'DemoPass!123'}));sh={'Authorization':'Bearer '+staff_login['token']}
            expect(c.post(f'/grooming/bookings/{bid}/start',headers=own,json={}),403)
            expect(c.post(f'/grooming/bookings/{bid}/complete',headers=sh,json={}),409)
            expect(c.post(f'/grooming/bookings/{bid}/start',headers=sh,json={}))
            expect(c.post(f'/bookings/{bid}/cancel',headers=own),409)
            saved=expect(c.post(f'/grooming/bookings/{bid}/complete',headers=sh,json={'service_notes':'Fictional runtime Grooming completed.'}))
            assert saved['booking']['status']=='COMPLETED' and len(saved['history'])==5
            assert saved['grooming_record']['completed_by_user_id']==staff
            expect(c.post('/auth/logout',headers=sh),204)
            expect(c.get('/me',headers=sh),401)
    finally:stop(p,f)
    p,f=start('restarted')
    try:
        with httpx.Client(base_url=base) as c:
            owner=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}));own={'Authorization':'Bearer '+owner['token']}
            assert expect(c.get(f'/grooming/bookings/{bid}',headers=own))==saved
            assert expect(c.get(f'/bookings/{bid}/history',headers=own))==saved['history']
            expect(c.post(f'/bookings/{bid}/reschedule',headers=own,json={'grooming_start':schedule['grooming_start']}),409)
    finally:stop(p,f)
    with create_engine(url).connect() as c:
        assert not c.execute(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')).scalar_one()
        for table in ('bookings','booking_events','grooming_records'):
            assert not c.execute(text("SELECT has_table_privilege(current_user,:t,'DELETE')"),{'t':table}).scalar_one()
        assert not c.execute(text("SELECT has_column_privilege(current_user,'grooming_records','started_at','UPDATE')")).scalar_one()
        assert not c.execute(text("SELECT has_table_privilege(current_user,'booking_events','UPDATE')")).scalar_one()
    engine.dispose()
    return {'real_http_processes':2,'customer_to_staff_grooming_completion':'PASS','history_events':5,
        'identical_completed_record_and_history_after_restart':True,'negative_role_transition_and_customer_changes_denied':True,
        'session_revocation_verified':True,'restricted_non_superuser_runtime':True,'booking_id':bid}


def catalog(config,prefix):
    with create_engine(config['frozen_test_url' if prefix=='frozen' else 'test_url']).connect() as c:
        version=c.execute(text('SELECT version()')).scalar_one()
        functions=c.execute(text("SELECT p.proname,p.prosrc,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'petops_%' ORDER BY p.proname")).all()
        expected={}
        for name in ('0003_rules.sql','0004_rules.sql'):
            source=(ROOT/'alembic/versions'/name).read_text()
            expected.update({n:body.strip() for n,body in re.findall(r'CREATE FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$;',source,re.S)})
        # 0002's preserved append-only function is an op.execute literal.
        # Parse its actual migration text instead of silently ignoring an extra function.
        legacy = ast.parse((ROOT/'alembic/versions/0002_harden_first_slice.py').read_text())
        for node in ast.walk(legacy):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                expected.update({n:body.strip() for n,body in re.findall(
                    r'CREATE FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$',node.value,re.S)})
        assert len(expected)==len(functions)
        assert all(expected[name]==body.strip() for name,body,_ in functions)
        triggers=[dict(r._mapping) for r in c.execute(text("SELECT tgname,tgenabled,pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE NOT tgisinternal ORDER BY tgname"))]
        constraints=[dict(r._mapping) for r in c.execute(text("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conname"))]
    payload={'postgresql_version':version,'revision':'0004','all_function_bodies_match_migration':True,
        'functions':[{'name':n,'definition':d} for n,_,d in functions],'triggers':triggers,'constraints':constraints}
    (OUT/(prefix+'-database-catalog.json')).write_text(json.dumps(payload,indent=2),encoding='utf-8')
    return {'installed_function_bodies_match':len(expected),'triggers_and_constraints_captured':True,'postgresql_version':version}


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','clean','upgrade','runtime','test','catalog','catalog-runtime'])
    p.add_argument('--prefix',choices=['dev','frozen'],default='dev');p.add_argument('--selection',nargs='*');args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.command=='prepare':prepare();return
    config=json.loads(CONFIG.read_text());before=fingerprint();commit=git('rev-parse','HEAD');bound=matches_commit(commit,before)
    if args.prefix=='frozen':assert bound,'Frozen verification refuses code not matching HEAD'
    record={'command':args.command,'prefix':args.prefix,'commit':commit,'tree':git('rev-parse',commit+'^{tree}'),
        'source_sha256':before,'started_at_utc':datetime.now(timezone.utc).isoformat(),'credentials_logged':False}
    failed=False
    try:
        if args.command=='test':
            command=['-m','pytest','-q','--tb=short',*(args.selection or [])]
            code=run(command,config['frozen_test_url' if args.prefix=='frozen' else 'test_url'],args.prefix+'-tests.txt',allow_failure=True)
            lines=(OUT/(args.prefix+'-tests.txt')).read_text().splitlines()
            result={'command':[sys.executable,*command],'exit_code':code,'pytest_summary':next((line for line in reversed(lines) if 'passed' in line or 'failed' in line),'See log')}
            failed=code!=0
        elif args.command=='catalog-runtime':
            result=catalog({'test_url':config['migration_url']},args.prefix+'-runtime')
        else:result=globals()[args.command](config,args.prefix)
        record['result']=result
    except Exception as exc:
        failed=True;record['result']={'verification_error_type':type(exc).__name__,'details':'Inspect retained operation logs; no successful result claimed'}
    record['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    record['source_matches_commit_before_and_after']=bound and fingerprint()==before and matches_commit(commit,before)
    record['source_unchanged_during_run']=fingerprint()==before
    record['wrapper_exit_code']=int(failed or not record['source_unchanged_during_run'] or (args.prefix=='frozen' and not record['source_matches_commit_before_and_after']))
    (OUT/(args.prefix+'-'+args.command+'-record.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record['result'],indent=2));sys.exit(record['wrapper_exit_code'])


if __name__=='__main__':main()
