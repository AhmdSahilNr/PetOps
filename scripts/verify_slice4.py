"""Commit-bound local PostgreSQL evidence; private credentials never printed.

prepare creates isolated databases, never resets existing databases. Test entity
cleanup is limited to the dedicated disposable loopback *_test database.
"""
import argparse, ast, json, os, re, subprocess, sys, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import psycopg
from psycopg import sql
from sqlalchemy import create_engine, make_url, text
from scripts import verify_slice3 as shared

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/slice4'
CONFIG=ROOT/'.local/slice4-config.json'
shared.OUT=OUT
run,empty=shared.run,shared.empty
fingerprint,git,matches_commit=shared.fingerprint,shared.git,shared.matches_commit


def prepare():
    if CONFIG.exists():print('Private Slice 4 config exists; no reset performed.');return
    old=json.loads((ROOT/'.local/postgres-config.json').read_text());template=make_url(old['test_url'])
    assert template.host=='127.0.0.1' and template.port==55432
    names={key:'petops_slice4_'+suffix for key,suffix in {
        'test_url':'dev_test','upgrade_url':'dev_upgrade_test','migration_url':'dev_runtime',
        'frozen_test_url':'frozen_test','frozen_upgrade_url':'frozen_upgrade_test','frozen_migration_url':'frozen_runtime'}.items()}
    with psycopg.connect(host=template.host,port=template.port,user='petops_local_admin',
        password=(ROOT/'.local/pgpassword').read_text().strip(),dbname='postgres',autocommit=True) as c:
        assert all(not c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone() for name in names.values()),'Dedicated database exists; no reset allowed'
        for name in names.values():c.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name),sql.Identifier(template.username)))
    config={key:template.set(database=name).render_as_string(hide_password=False) for key,name in names.items()}
    for prefix in ('','frozen_'):
        config[prefix+'runtime_url']=make_url(old['runtime_url']).set(database=names[prefix+'migration_url']).render_as_string(hide_password=False)
    CONFIG.write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('Created separate dev/frozen test, upgrade and runtime databases; no credentials exported.')


def chosen(config,key,prefix):return config[('frozen_' if prefix=='frozen' else '')+key]


def clean(config,prefix):
    url=chosen(config,'test_url',prefix);engine=create_engine(url)
    assert empty(engine),'Clean proof requires empty DB; no reset performed'
    for args,label in [(['upgrade','head'],'clean-migration'),(['upgrade','head'],'repeat-migration'),(['check'],'schema-check')]:
        run(['-m','alembic',*args],url,prefix+'-'+label+'.txt')
    with engine.connect() as c:assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0005'
    engine.dispose();return {'empty_database_observed':True,'revision':'0005','repeat_and_model_schema_agreement':'PASS'}


def upgrade(config,prefix):
    url=chosen(config,'upgrade_url',prefix);engine=create_engine(url);assert empty(engine),'No reset permitted'
    run(['-m','alembic','upgrade','0004'],url,prefix+'-legacy-schema.txt')
    ids={k:uuid.uuid4() for k in ('owner','admin','staff','customer','pet','gservice','bservice','gbooking','bbooking','badbooking','unit','allocation','window','grecord','submitted','started','completed')}
    now=datetime.now(timezone.utc);later=now+timedelta(days=2)
    from app.services import business_today
    day=business_today()
    with engine.begin() as c:
        for who,role in [('owner','CUSTOMER'),('admin','ADMIN'),('staff','STAFF')]:
            c.execute(text('INSERT INTO users(id,email,password_hash,role,is_active,created_at) VALUES (:id,:email,\'not-a-login-hash\',:role,true,:now)'),{'id':ids[who],'email':'slice4.upgrade.'+who+'@petops.example','role':role,'now':now})
        c.execute(text("INSERT INTO customers(id,user_id,display_name,created_at,updated_at) VALUES (:customer,:owner,'Fictional Upgrade Customer',:now,:now)"),{**ids,'now':now})
        c.execute(text("INSERT INTO pets(id,customer_id,name,created_at,updated_at) VALUES (:pet,:customer,'Fictional Upgrade Pet',:now,:now)"),{**ids,'now':now})
        for who,kind,duration in [('gservice','GROOMING',60),('bservice','BOARDING',None)]:
            c.execute(text('INSERT INTO services(id,name,service_type,is_active,duration_minutes,created_at) VALUES (:id,:name,:kind,true,:duration,:now)'),{'id':ids[who],'name':'Fictional Upgrade '+kind,'kind':kind,'duration':duration,'now':now})
        c.execute(text('INSERT INTO staff_availability(id,staff_user_id,starts_at,ends_at,is_active,updated_by_user_id,updated_at) VALUES (:window,:staff,:lo,:hi,true,:admin,:now)'),{**ids,'lo':now-timedelta(days=1),'hi':now+timedelta(days=10),'now':now})
        c.execute(text("INSERT INTO bookings(id,customer_id,pet_id,service_id,booking_type,status,grooming_start,grooming_duration_minutes,assigned_staff_user_id,staff_start,staff_end,created_by_user_id,created_at,updated_at) VALUES (:gbooking,:customer,:pet,:gservice,'GROOMING','SUBMITTED',:lo,60,:staff,:lo,:hi,:owner,:now,:now)"),{**ids,'lo':later,'hi':later+timedelta(hours=1),'now':now})
        c.execute(text("INSERT INTO booking_events(id,booking_id,event_type,new_status,actor_user_id,created_at) VALUES (:submitted,:gbooking,'BOOKING_SUBMITTED','SUBMITTED',:owner,:now)"),{**ids,'now':now})
        c.execute(text("UPDATE bookings SET status='CONFIRMED' WHERE id=:gbooking"),ids)
        c.execute(text("UPDATE bookings SET status='IN_PROGRESS' WHERE id=:gbooking"),ids)
        c.execute(text('INSERT INTO grooming_records(id,booking_id,started_by_user_id,started_at) VALUES (:grecord,:gbooking,:staff,:now)'),{**ids,'now':now})
        c.execute(text("INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:started,:gbooking,'GROOMING_STARTED','CONFIRMED','IN_PROGRESS',:staff,:now)"),{**ids,'now':now})
        c.execute(text("UPDATE bookings SET status='COMPLETED' WHERE id=:gbooking"),ids)
        c.execute(text("UPDATE grooming_records SET completed_by_user_id=:admin,completed_at=:now,service_notes='Fictional preserved Grooming completion' WHERE id=:grecord"),{**ids,'now':now+timedelta(microseconds=1)})
        c.execute(text("INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:completed,:gbooking,'GROOMING_COMPLETED','IN_PROGRESS','COMPLETED',:admin,:now)"),{**ids,'now':now+timedelta(microseconds=1)})
        c.execute(text("INSERT INTO accommodations(id,name,category,capacity,is_active,updated_by_user_id,updated_at) VALUES (:unit,'Fictional Upgrade Unit','Fictional',2,true,:admin,:now)"),{**ids,'now':now})
        for key in ('bbooking','badbooking'):
            c.execute(text("INSERT INTO bookings(id,customer_id,pet_id,service_id,booking_type,status,boarding_start,boarding_end,created_by_user_id,created_at,updated_at) VALUES (:id,:customer,:pet,:bservice,'BOARDING','SUBMITTED',:lo,:hi,:owner,:now,:now)"),{**ids,'id':ids[key],'lo':day,'hi':day+timedelta(days=2),'now':now})
        c.execute(text('INSERT INTO boarding_allocations(id,booking_id,accommodation_id,starts_on,ends_on,created_by_user_id,created_at) VALUES (:allocation,:bbooking,:unit,:lo,:hi,:admin,:now)'),{**ids,'lo':day,'hi':day+timedelta(days=2),'now':now})
        c.execute(text("UPDATE bookings SET status='CONFIRMED' WHERE id=:bbooking"),ids)
        c.execute(text("UPDATE bookings SET status='CHECKED_IN' WHERE id=:badbooking"),ids)
    with engine.connect() as c:
        before=[tuple(r) for r in c.execute(text('SELECT id,booking_id,started_by_user_id,started_at,completed_by_user_id,completed_at,service_notes FROM grooming_records'))]
    assert run(['-m','alembic','upgrade','head'],url,prefix+'-legacy-anomaly-denied.txt',allow_failure=True)!=0
    with engine.begin() as c:
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0004'
        assert c.execute(text("SELECT to_regclass('public.boarding_stays')")).scalar_one() is None
        c.execute(text("UPDATE bookings SET status='SUBMITTED' WHERE id=:badbooking"),ids) # restore intentional synthetic anomaly only
    run(['-m','alembic','upgrade','head'],url,prefix+'-populated-upgrade.txt')
    with engine.connect() as c:
        assert before==[tuple(r) for r in c.execute(text('SELECT id,booking_id,started_by_user_id,started_at,completed_by_user_id,completed_at,service_notes FROM grooming_records'))]
        assert tuple(c.execute(text('SELECT id,booking_id,accommodation_id,created_by_user_id,created_at,released_at FROM boarding_allocations')).one())==(ids['allocation'],ids['bbooking'],ids['unit'],ids['admin'],now,None)
        assert c.execute(text('SELECT count(*) FROM boarding_stays')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM booking_events')).scalar_one()==3
    engine.dispose();return {'populated_0004_to_0005':'PASS','grooming_completion_links_notes_actor_times_preserved':True,
        'boarding_reservation_actor_time_preserved':True,'legacy_anomaly_denied_and_migration_rolled_back':True,'no_stay_history_fabricated':True}


def runtime(config,prefix):
    migration=chosen(config,'migration_url',prefix);url=chosen(config,'runtime_url',prefix);engine=create_engine(migration)
    assert empty(engine),'Runtime proof requires its own empty DB; no reset or reuse'
    run(['-m','alembic','upgrade','head'],migration,prefix+'-runtime-migration.txt')
    run(['-m','scripts.seed_demo'],migration,prefix+'-seed.txt')
    with engine.begin() as c:
        c.execute(text('GRANT USAGE ON SCHEMA public TO petops_runtime'))
        c.execute(text('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM petops_runtime'))
        c.execute(text('GRANT SELECT,INSERT ON users,user_sessions,customers,pets,bookings,booking_events,staff_availability,accommodations,boarding_allocations,grooming_records,boarding_stays,boarding_notes TO petops_runtime'))
        c.execute(text('GRANT UPDATE ON customers,pets,bookings,staff_availability,accommodations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (scheduling_version) ON users TO petops_runtime'))
        c.execute(text('GRANT SELECT ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (duration_minutes,updated_by_user_id,updated_at) ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (released_at,released_by_user_id) ON boarding_allocations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (completed_at,completed_by_user_id,service_notes) ON grooming_records TO petops_runtime'))
        c.execute(text('GRANT UPDATE (stay_started_at,stay_started_by_user_id,checked_out_at,checked_out_by_user_id,completed_at,completed_by_user_id) ON boarding_stays TO petops_runtime'))
        c.execute(text('GRANT DELETE ON pets,user_sessions TO petops_runtime'))
        staff=str(c.execute(text("SELECT id FROM users WHERE email='staff.demo@petops.example'")).scalar_one())
        unit=str(c.execute(text("SELECT id FROM accommodations WHERE name='Fictional Demo Unit'")).scalar_one())
    base='http://127.0.0.1:58084'
    def start(label):
        try:httpx.get(base+'/health',timeout=1)
        except httpx.HTTPError:pass
        else:raise RuntimeError('Proof port occupied; existing process left untouched')
        f=(OUT/(prefix+'-http-'+label+'.txt')).open('w',encoding='utf-8')
        p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','58084'],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':url,'PETOPS_ENV':'development'},stdout=f,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(100):
            try:
                if httpx.get(base+'/health',timeout=1).status_code==200:return p,f
            except httpx.HTTPError:pass
            if p.poll() is not None:break
            time.sleep(.2)
        p.terminate();p.wait(timeout=10);f.close();raise RuntimeError('HTTP readiness failed')
    def stop(p,f):p.terminate();p.wait(timeout=10);f.close()
    def expect(r,code=200):
        assert r.status_code==code,(r.status_code,r.text)
        return r.json() if code!=204 else None
    from app.services import business_today
    today=business_today();email='slice4.runtime.'+uuid.uuid4().hex[:12]+'@petops.example'
    p,f=start('first')
    try:
        with httpx.Client(base_url=base) as c:
            assert c.get('/').status_code==c.get('/static/boarding.js').status_code==200
            expect(c.get('/boarding/bookings'),401)
            expect(c.post('/auth/register',json={'email':email,'password':'FictionalPass!123','display_name':'Fictional Boarding Customer'}),201)
            owner=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}));own={'Authorization':'Bearer '+owner['token']}
            pet=expect(c.post('/pets',headers=own,json={'name':'Fictional Boarding Pet'}),201)
            service=next(s for s in expect(c.get('/services',headers=own)) if s['service_type']=='BOARDING')
            schedule={'service_id':service['id'],'boarding_start':today.isoformat(),'boarding_end':(today+timedelta(days=2)).isoformat()}
            assert expect(c.post('/availability',headers=own,json=schedule))['available']
            b=expect(c.post('/bookings',headers=own,json={'pet_id':pet['id'],**schedule}),201);bid=b['id']
            admin=expect(c.post('/auth/login',json={'email':'admin.demo@petops.example','password':'DemoPass!123'}));ah={'Authorization':'Bearer '+admin['token']}
            expect(c.post(f'/admin/bookings/{bid}/status',headers=ah,json={'status':'CONFIRMED'}),409)
            expect(c.put(f'/admin/bookings/{bid}/accommodation',headers=ah,json={'accommodation_id':unit}))
            now=datetime.now(timezone.utc)
            expect(c.put(f'/admin/bookings/{bid}/staff',headers=ah,json={'staff_user_id':staff,'starts_at':(now+timedelta(minutes=5)).isoformat(),'ends_at':(now+timedelta(minutes=25)).isoformat()}))
            expect(c.post(f'/admin/bookings/{bid}/status',headers=ah,json={'status':'CONFIRMED'}))
            sl=expect(c.post('/auth/login',json={'email':'staff.demo@petops.example','password':'DemoPass!123'}));sh={'Authorization':'Bearer '+sl['token']}
            expect(c.post(f'/boarding/bookings/{bid}/check-in',headers=own,json={}),403)
            expect(c.post(f'/boarding/bookings/{bid}/check-out',headers=sh,json={}),409)
            expect(c.post(f'/boarding/bookings/{bid}/check-in',headers=sh,json={}))
            expect(c.post(f'/bookings/{bid}/cancel',headers=own),409)
            expect(c.post(f'/boarding/bookings/{bid}/start-stay',headers=sh,json={}))
            expect(c.post(f'/boarding/bookings/{bid}/notes',headers=sh,json={'note':'Fictional stay observation recorded.'}),201)
            out=expect(c.post(f'/boarding/bookings/{bid}/check-out',headers=sh,json={}))
            assert out['allocation_history'][-1]['released_at']==out['boarding_stay']['checked_out_at']
            saved=expect(c.post(f'/boarding/bookings/{bid}/complete',headers=sh,json={}))
            assert saved['booking']['status']=='COMPLETED' and len(saved['history'])==9
            expect(c.post('/auth/logout',headers=sh),204);expect(c.get('/me',headers=sh),401)
    finally:stop(p,f)
    p,f=start('restarted')
    try:
        with httpx.Client(base_url=base) as c:
            owner=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}));own={'Authorization':'Bearer '+owner['token']}
            assert expect(c.get(f'/boarding/bookings/{bid}',headers=own))==saved
            assert expect(c.get(f'/bookings/{bid}/history',headers=own))==saved['history']
            expect(c.post(f'/boarding/bookings/{bid}/notes',headers=own,json={'note':'forbidden'}),403)
    finally:stop(p,f)
    with create_engine(url).connect() as c:
        assert not c.execute(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')).scalar_one()
        for table in ('bookings','booking_events','boarding_stays','boarding_notes'):
            assert not c.execute(text("SELECT has_table_privilege(current_user,:t,'DELETE')"),{'t':table}).scalar_one()
        for table,column in [('boarding_stays','checked_in_at'),('boarding_notes','note'),('booking_events','actor_user_id')]:
            assert not c.execute(text('SELECT has_column_privilege(current_user,:t,:col,\'UPDATE\')'),{'t':table,'col':column}).scalar_one()
    engine.dispose();return {'fresh_runtime_database':True,'real_http_processes':2,'customer_to_staff_boarding_completion':'PASS',
        'history_events':9,'allocation_release_matches_checkout_actor_time':True,'identical_stay_notes_and_history_after_restart':True,
        'negative_role_state_and_customer_change_denials':True,'restricted_non_superuser_runtime':True,'booking_id':bid}


def catalog(config,prefix,runtime=False):
    url=chosen(config,'migration_url' if runtime else 'test_url',prefix)
    with create_engine(url).connect() as c:
        functions=c.execute(text("SELECT p.proname,p.prosrc,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'petops_%' ORDER BY p.proname")).all()
        expected={}
        tree=ast.parse((ROOT/'alembic/versions/0002_harden_first_slice.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                expected.update({name:body.strip() for name,body in re.findall(r'CREATE FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$',node.value,re.S)})
        for name in ('0003_rules.sql','0004_rules.sql','0005_rules.sql'):
            expected.update({name:body.strip() for name,body in re.findall(r'CREATE (?:OR REPLACE )?FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$;',(ROOT/'alembic/versions'/name).read_text(),re.S)})
        assert set(expected)=={n for n,_,_ in functions}
        assert all(expected[n]==body.strip() for n,body,_ in functions)
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0005'
        payload={'postgresql_version':c.execute(text('SELECT version()')).scalar_one(),'revision':'0005',
            'all_function_bodies_match_latest_migration':True,'functions':[{'name':n,'definition':d} for n,_,d in functions],
            'triggers':[dict(r._mapping) for r in c.execute(text("SELECT tgname,tgenabled,pg_get_triggerdef(oid) AS definition FROM pg_trigger WHERE NOT tgisinternal ORDER BY tgname"))],
            'constraints':[dict(r._mapping) for r in c.execute(text("SELECT conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY conname"))]}
    (OUT/(prefix+('-runtime' if runtime else '')+'-database-catalog.json')).write_text(json.dumps(payload,indent=2),encoding='utf-8')
    return {'installed_function_bodies_match_latest_migration':len(expected),'triggers_and_constraints_captured':True,'postgresql_version':payload['postgresql_version']}


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','clean','upgrade','runtime','test','catalog','catalog-runtime'])
    p.add_argument('--prefix',choices=['dev','frozen'],default='dev');p.add_argument('--selection',nargs='*');args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.command=='prepare':prepare();return
    config=json.loads(CONFIG.read_text());before=fingerprint();commit=git('rev-parse','HEAD');bound=matches_commit(commit,before)
    if args.prefix=='frozen':assert bound,'Frozen verification refuses uncommitted source'
    record={'command':args.command,'prefix':args.prefix,'commit':commit,'tree':git('rev-parse',commit+'^{tree}'),
        'source_sha256':before,'started_at_utc':datetime.now(timezone.utc).isoformat(),'credentials_logged':False};failed=False
    try:
        if args.command=='test':
            command=['-m','pytest','-q','--tb=short',*(args.selection or [])]
            code=run(command,chosen(config,'test_url',args.prefix),args.prefix+'-tests.txt',allow_failure=True)
            lines=(OUT/(args.prefix+'-tests.txt')).read_text().splitlines()
            result={'command':[sys.executable,*command],'exit_code':code,'pytest_summary':next((s for s in reversed(lines) if 'passed' in s or 'failed' in s),'See log')};failed=code!=0
        elif args.command in ('catalog','catalog-runtime'):result=catalog(config,args.prefix,args.command=='catalog-runtime')
        else:result=globals()[args.command](config,args.prefix)
        record['result']=result
    except Exception as exc:
        failed=True;record['result']={'verification_error_type':type(exc).__name__,'details':'Inspect retained logs; no successful result claimed'}
    record['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    record['source_unchanged_during_run']=fingerprint()==before
    record['source_matches_commit_before_and_after']=bound and record['source_unchanged_during_run'] and matches_commit(commit,before)
    record['wrapper_exit_code']=int(failed or not record['source_unchanged_during_run'] or (args.prefix=='frozen' and not record['source_matches_commit_before_and_after']))
    (OUT/(args.prefix+'-'+args.command+'-record.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record['result'],indent=2));sys.exit(record['wrapper_exit_code'])


if __name__=='__main__':main()
