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
OUT=ROOT/'docs/evidence/slice5'
CONFIG=ROOT/'.local/slice5-config.json'
shared.OUT=OUT
run,empty=shared.run,shared.empty
fingerprint,git,matches_commit=shared.fingerprint,shared.git,shared.matches_commit


def prepare():
    if CONFIG.exists():print('Private Slice 5 config exists; no reset performed.');return
    old=json.loads((ROOT/'.local/postgres-config.json').read_text());template=make_url(old['test_url'])
    assert template.host=='127.0.0.1' and template.port==55432
    names={key:'petops_slice5_'+suffix for key,suffix in {
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
    with engine.connect() as c:assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0006'
    engine.dispose();return {'empty_database_observed':True,'revision':'0006','repeat_and_model_schema_agreement':'PASS'}


def upgrade(config,prefix):
    import hashlib
    url=chosen(config,'upgrade_url',prefix);engine=create_engine(url);assert empty(engine),'No reset permitted'
    run(['-m','alembic','upgrade','0005'],url,prefix+'-legacy-schema.txt')
    run(['-m','scripts.seed_demo'],url,prefix+'-legacy-seed.txt')
    # Exercise genuine old operational services on 0005 before adding notification tables.
    code='''
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User,Customer,Pet,Service,Accommodation
from app.services import create_booking,admin_change_status,business_today
from app.models import BookingStatus
from app.resource_routes import assign_staff,allocate_accommodation
from app.schemas import StaffAssignmentIn,AllocationIn,InputModel,GroomingCompleteIn,BoardingNoteIn
from app.grooming_routes import start_work,complete_work
from app.boarding_routes import check_in,start_stay,check_out,complete_stay,add_stay_note
with SessionLocal() as db:
    users={u.role.value:u for u in db.scalars(select(User))};owner=users['CUSTOMER'];admin=users['ADMIN'];staff=users['STAFF']
    customer=db.scalar(select(Customer));pet=Pet(customer_id=customer.id,name='Fictional retained pet');db.add(pet);db.commit()
    services={s.service_type.value:s for s in db.scalars(select(Service).where(Service.is_active))}
    g=create_booking(db,customer,owner,pet.id,services['GROOMING'].id,grooming_start=datetime.now(timezone.utc)+timedelta(days=1))
    assign_staff(g.id,StaffAssignmentIn(staff_user_id=staff.id),admin,db);admin_change_status(db,g,admin,BookingStatus.CONFIRMED)
    start_work(g.id,InputModel(),staff,db);complete_work(g.id,GroomingCompleteIn(service_notes='Fictional retained Grooming record'),staff,db)
    b=create_booking(db,customer,owner,pet.id,services['BOARDING'].id,boarding_start=business_today(),boarding_end=business_today()+timedelta(days=2))
    allocate_accommodation(b.id,AllocationIn(accommodation_id=db.scalar(select(Accommodation)).id),admin,db);admin_change_status(db,b,admin,BookingStatus.CONFIRMED)
    check_in(b.id,InputModel(),admin,db);start_stay(b.id,InputModel(),admin,db);add_stay_note(b.id,BoardingNoteIn(note='Fictional retained stay note'),admin,db);check_out(b.id,InputModel(),admin,db);complete_stay(b.id,InputModel(),admin,db)
print('Completed fictional Grooming and Boarding on revision 0005')
'''
    run(['-c',code],url,prefix+'-legacy-workflows.txt')
    tables=['users','customers','pets','services','bookings','booking_events','grooming_records','boarding_stays','boarding_notes','boarding_allocations','staff_availability','accommodations']
    def snapshot():
        with engine.connect() as c:
            return {t:{'count':c.execute(text('SELECT count(*) FROM '+t)).scalar_one(),
                'sha256':hashlib.sha256(c.execute(text("SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY id),'[]'::jsonb)::text FROM "+t+' t')).scalar_one().encode()).hexdigest()} for t in tables}
    before=snapshot();assert before['grooming_records']['count']==before['boarding_stays']['count']==1
    run(['-m','alembic','upgrade','head'],url,prefix+'-populated-upgrade.txt')
    assert snapshot()==before
    with engine.connect() as c:
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0006'
        assert c.execute(text('SELECT count(*) FROM notifications')).scalar_one()==0
        assert c.execute(text('SELECT count(*) FROM management_events')).scalar_one()==0
        assert tuple(c.execute(text('SELECT enabled,lead_minutes,updated_by_user_id,updated_at FROM notification_settings')).one())==(False,None,None,None)
    (OUT/(prefix+'-upgrade-preserved-rows.json')).write_text(json.dumps(before,indent=2),encoding='utf-8')
    engine.dispose();return {'populated_0005_to_0006':'PASS','completed_grooming_and_boarding_preserved':True,
        'all_legacy_table_hashes_unchanged':True,'no_historical_notifications_fabricated':True,'reminders_initially_disabled_and_unconfigured':True}


def runtime(config,prefix):
    migration=chosen(config,'migration_url',prefix);url=chosen(config,'runtime_url',prefix);engine=create_engine(migration)
    assert empty(engine),'Runtime proof requires a fresh isolated DB; no reset permitted'
    run(['-m','alembic','upgrade','head'],migration,prefix+'-runtime-migration.txt')
    run(['-m','scripts.seed_demo'],migration,prefix+'-seed.txt')
    with engine.begin() as c:
        c.execute(text('GRANT USAGE ON SCHEMA public TO petops_runtime'))
        c.execute(text('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM petops_runtime'))
        c.execute(text('GRANT SELECT,INSERT ON users,user_sessions,customers,pets,bookings,booking_events,staff_availability,accommodations,boarding_allocations,grooming_records,boarding_stays,boarding_notes,notifications,management_events,services TO petops_runtime'))
        c.execute(text('GRANT UPDATE ON customers,pets,bookings,staff_availability,accommodations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (scheduling_version,email,password_hash,is_active) ON users TO petops_runtime'))
        c.execute(text('GRANT UPDATE (name,is_active,duration_minutes,updated_by_user_id,updated_at) ON services TO petops_runtime'))
        c.execute(text('GRANT UPDATE (released_at,released_by_user_id) ON boarding_allocations TO petops_runtime'))
        c.execute(text('GRANT UPDATE (completed_at,completed_by_user_id,service_notes) ON grooming_records TO petops_runtime'))
        c.execute(text('GRANT UPDATE (stay_started_at,stay_started_by_user_id,checked_out_at,checked_out_by_user_id,completed_at,completed_by_user_id) ON boarding_stays TO petops_runtime'))
        c.execute(text('GRANT SELECT,UPDATE ON notification_settings TO petops_runtime'))
        c.execute(text('GRANT UPDATE (read_at) ON notifications TO petops_runtime'))
        c.execute(text('GRANT DELETE ON pets,user_sessions TO petops_runtime'))
        staff=str(c.execute(text("SELECT id FROM users WHERE email='staff.demo@petops.example'")).scalar_one())
        unit=str(c.execute(text("SELECT id FROM accommodations WHERE name='Fictional Demo Unit'")).scalar_one())
    base='http://127.0.0.1:58086'
    def start(label):
        try:httpx.get(base+'/health',timeout=1)
        except httpx.HTTPError:pass
        else:raise RuntimeError('Proof port occupied; existing process left untouched')
        f=(OUT/(prefix+'-http-'+label+'.txt')).open('w',encoding='utf-8')
        p=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','58086'],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':url,'PETOPS_ENV':'development','PETOPS_REMINDER_POLL_SECONDS':'0.2'},stdout=f,stderr=subprocess.STDOUT,
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
    today=business_today();email='slice5.runtime.'+uuid.uuid4().hex[:12]+'@petops.example'
    p,f=start('first')
    try:
        with httpx.Client(base_url=base) as c:
            assert c.get('/').status_code==c.get('/static/operations.js').status_code==200
            expect(c.get('/notifications'),401);expect(c.get('/admin/dashboard',params={'from_date':today,'to_date':today}),401)
            expect(c.post('/auth/register',json={'email':email,'password':'FictionalPass!123','display_name':'Fictional Slice 5 Customer'}),201)
            owner=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}));own={'Authorization':'Bearer '+owner['token']}
            pet=expect(c.post('/pets',headers=own,json={'name':'Fictional Slice 5 Pet'}),201)
            services=expect(c.get('/services',headers=own));g=next(s for s in services if s['service_type']=='GROOMING')
            b=expect(c.post('/bookings',headers=own,json={'pet_id':pet['id'],'service_id':g['id'],'grooming_start':(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}),201);bid=b['id']
            admin=expect(c.post('/auth/login',json={'email':'admin.demo@petops.example','password':'DemoPass!123'}));ah={'Authorization':'Bearer '+admin['token']}
            assert expect(c.get('/admin/notification-settings',headers=ah))['enabled'] is False
            expect(c.put(f'/admin/bookings/{bid}/staff',headers=ah,json={'staff_user_id':staff}))
            expect(c.post(f'/admin/bookings/{bid}/status',headers=ah,json={'status':'CONFIRMED'}))
            expect(c.put('/admin/notification-settings',headers=ah,json={'enabled':True,'lead_minutes':10}))
            # Actual lifespan poll, not a manual call; wait for its persisted notice.
            for _ in range(60):
                inbox=expect(c.get('/notifications',headers=own))
                if any(n['kind']=='BOOKING_REMINDER' for n in inbox['items']):break
                time.sleep(.2)
            assert {n['kind'] for n in inbox['items']}=={'BOOKING_SUBMITTED','BOOKING_CONFIRMED','BOOKING_REMINDER'}
            notice=next(n for n in inbox['items'] if n['kind']=='BOOKING_REMINDER')
            marked=expect(c.post('/notifications/'+notice['id']+'/read',headers=own,json={}))
            assert marked['read_at'] and marked['lead_minutes']==10
            sl=expect(c.post('/auth/login',json={'email':'staff.demo@petops.example','password':'DemoPass!123'}));sh={'Authorization':'Bearer '+sl['token']}
            assert [n['kind'] for n in expect(c.get('/notifications',headers=sh))['items']]==['STAFF_ASSIGNED']
            expect(c.get('/notifications/'+notice['id'],headers=sh),404)
            expect(c.get('/admin/staff',headers=own),403);expect(c.get('/admin/dashboard',params={'from_date':today,'to_date':today},headers=sh),403)
            newstaff=expect(c.post('/admin/staff',headers=ah,json={'email':'created.staff@petops.example','password':'FictionalPass!123'}),201)
            expect(c.put('/admin/staff/'+newstaff['id'],headers=ah,json={'email':'updated.staff@petops.example','is_active':True}))
            createdservice=expect(c.post('/admin/services',headers=ah,json={'name':'Fictional Admin Grooming','service_type':'GROOMING','duration_minutes':45}),201)
            expect(c.put('/admin/services/'+createdservice['id'],headers=ah,json={'name':'Fictional Admin Grooming updated','is_active':False,'duration_minutes':30}))
            expect(c.post(f'/grooming/bookings/{bid}/start',headers=sh,json={}))
            gd=expect(c.post(f'/grooming/bookings/{bid}/complete',headers=sh,json={'service_notes':'Fictional Slice 5 completed service'}))
            bs=next(s for s in services if s['service_type']=='BOARDING')
            bb=expect(c.post('/bookings',headers=own,json={'pet_id':pet['id'],'service_id':bs['id'],'boarding_start':today.isoformat(),'boarding_end':(today+timedelta(days=2)).isoformat()}),201)
            expect(c.put(f"/admin/bookings/{bb['id']}/accommodation",headers=ah,json={'accommodation_id':unit}))
            expect(c.post(f"/admin/bookings/{bb['id']}/status",headers=ah,json={'status':'CONFIRMED'}))
            for action in ('check-in','start-stay','check-out','complete'):
                bd=expect(c.post(f"/boarding/bookings/{bb['id']}/{action}",headers=ah,json={}))
            report=expect(c.get('/admin/dashboard',params={'from_date':today,'to_date':today},headers=ah))
            assert report['total_bookings']==2 and report['completed_services_by_type']=={'GROOMING':1,'BOARDING':1}
            assert report['boarding_current']['physically_occupied']==0
            history=expect(c.get('/admin/history',headers=ah));assert len(history['items'])==2
            audit=expect(c.get('/admin/management-history',headers=ah));assert len(audit)==5 and 'password_hash' not in str(audit)
    finally:stop(p,f)
    p,f=start('restarted')
    try:
        with httpx.Client(base_url=base) as c:
            owner=expect(c.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}));own={'Authorization':'Bearer '+owner['token']}
            assert expect(c.get('/notifications/'+notice['id'],headers=own))==marked
            assert expect(c.get(f'/grooming/bookings/{bid}',headers=own))==gd
            assert expect(c.get(f"/boarding/bookings/{bb['id']}",headers=own))==bd
            assert len([n for n in expect(c.get('/notifications',headers=own))['items'] if n['kind']=='BOOKING_REMINDER'])==1
    finally:stop(p,f)
    with create_engine(url).connect() as c:
        assert not c.execute(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')).scalar_one()
        for table in ('notifications','management_events','notification_settings','bookings','booking_events'):
            assert not c.execute(text("SELECT has_table_privilege(current_user,:t,'DELETE')"),{'t':table}).scalar_one()
        for table,column in [('notifications','recipient_user_id'),('management_events','details'),('users','role'),('services','service_type')]:
            assert not c.execute(text("SELECT has_column_privilege(current_user,:t,:col,'UPDATE')"),{'t':table,'col':column}).scalar_one()
    engine.dispose();return {'fresh_runtime_database':True,'real_http_processes':2,'automatic_lifespan_reminder_persisted':True,
        'customer_and_staff_inboxes_and_read_persistence':'PASS','management_and_dashboard_runtime':'PASS',
        'grooming_and_boarding_completion_retained':'PASS','restart_retains_records_history_and_notices':True,
        'restricted_non_superuser_runtime':True,'grooming_booking_id':bid,'boarding_booking_id':bb['id']}



def catalog(config,prefix,runtime=False):
    url=chosen(config,'migration_url' if runtime else 'test_url',prefix)
    with create_engine(url).connect() as c:
        functions=c.execute(text("SELECT p.proname,p.prosrc,pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'petops_%' ORDER BY p.proname")).all()
        expected={}
        tree=ast.parse((ROOT/'alembic/versions/0002_harden_first_slice.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                expected.update({name:body.strip() for name,body in re.findall(r'CREATE FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$',node.value,re.S)})
        for name in ('0003_rules.sql','0004_rules.sql','0005_rules.sql','0006_rules.sql'):
            expected.update({name:body.strip() for name,body in re.findall(r'CREATE (?:OR REPLACE )?FUNCTION (\w+)\(.*?AS \$\$(.*?)\$\$;',(ROOT/'alembic/versions'/name).read_text(),re.S)})
        assert set(expected)=={n for n,_,_ in functions}
        assert all(expected[n]==body.strip() for n,body,_ in functions)
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0006'
        payload={'postgresql_version':c.execute(text('SELECT version()')).scalar_one(),'revision':'0006',
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
