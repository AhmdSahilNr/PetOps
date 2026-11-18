"""Execute migrations, drift checks, tests and real HTTP persistence on local PG.

Run after setup_local_postgres, from repository root. Uses only dedicated local
databases from ignored config. Never logs passwords/connection URLs.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs' / 'evidence'
CONFIG = ROOT / '.local' / 'postgres-config.json'


def run(args, url, logfile, extra_env=None):
    env = {**os.environ, 'PETOPS_DATABASE_URL':url, **(extra_env or {})}
    with (EVIDENCE/logfile).open('w',encoding='utf-8') as stream:
        result = subprocess.run([sys.executable,*args],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    print(f"{logfile}: exit {result.returncode}",flush=True)
    if result.returncode:
        raise SystemExit(f'Check docs/evidence/{logfile}')


def main():
    EVIDENCE.mkdir(exist_ok=True)
    config = json.loads(CONFIG.read_text())
    migration = config['migration_url']
    runtime = config['runtime_url']
    runtime_only = '--runtime-only' in sys.argv
    engine = create_engine(migration)
    with engine.connect() as conn:
        initial_tables = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
        if initial_tables and not runtime_only:
            raise SystemExit('Demo database must be clean for this evidence run. No records removed.')
        version = conn.execute(text('SELECT version()')).scalar_one()
    if not runtime_only:
        print('Verified empty PostgreSQL demo database',flush=True)
        run(['-m','alembic','upgrade','head'],migration,'postgres-clean-migrations.txt')
        run(['-m','alembic','upgrade','head'],migration,'postgres-repeat-migrations.txt')
        run(['-m','alembic','check'],migration,'postgres-schema-check.txt')
        run(['-m','alembic','current'],migration,'postgres-revision.txt')
        run(['-m','scripts.seed_demo'],migration,'postgres-seed.txt')
    with engine.begin() as conn:
        conn.execute(text('GRANT USAGE ON SCHEMA public TO petops_runtime'))
        conn.execute(text('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM petops_runtime'))
        conn.execute(text('GRANT SELECT, INSERT ON users, user_sessions, customers, pets, bookings, booking_events TO petops_runtime'))
        conn.execute(text('GRANT UPDATE ON customers, pets, bookings TO petops_runtime'))
        conn.execute(text('GRANT DELETE ON pets TO petops_runtime'))
        conn.execute(text('GRANT SELECT ON services TO petops_runtime'))
    # Use actual processes/HTTP, not TestClient; terminate each server cleanly.
    base = 'http://127.0.0.1:58080'
    def start_server(logname):
        stream = (EVIDENCE/logname).open('w',encoding='utf-8')
        process = subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','58080'],cwd=ROOT,
            env={**os.environ,'PETOPS_DATABASE_URL':runtime,'PETOPS_ENV':'development'},stdout=stream,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('HTTP server exited; inspect server log')
            try:
                if httpx.get(base+'/health',timeout=1).status_code == 200:
                    return process,stream
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        process.terminate(); process.wait(timeout=10); stream.close()
        raise RuntimeError('HTTP server readiness timeout')
    def stop_server(process,stream):
        process.terminate(); process.wait(timeout=10); stream.close()
    def expect(response,status):
        assert response.status_code == status, (response.status_code,response.text)
        return response.json() if status != 204 else None
    process,stream = start_server('postgres-http-first.txt')
    try:
        with httpx.Client(base_url=base) as client:
            expect(client.get('/bookings'),401)
            email = f'runtime.{uuid.uuid4().hex[:12]}@petops.example'
            user = expect(client.post('/auth/register',json={'email':email,'password':'FictionalPass!123','display_name':'Runtime Demo'}),201)
            token = expect(client.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}),200)['token']
            client.headers['Authorization'] = f'Bearer {token}'
            pet = expect(client.post('/pets',json={'name':'Persistence Demo Pet'}),201)
            services = expect(client.get('/services'),200)
            grooming = next(s for s in services if s['service_type']=='GROOMING')
            booking = expect(client.post('/bookings',json={'pet_id':pet['id'],'service_id':grooming['id'],'grooming_start':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()}),201)
            bid = booking['id']
            expect(client.post(f'/bookings/{bid}/reschedule',json={'grooming_start':(datetime.now(timezone.utc)+timedelta(days=4)).isoformat()}),200)
            expect(client.post(f'/bookings/{bid}/cancel'),200)
            history_before = expect(client.get(f'/bookings/{bid}/history'),200)
    finally:
        stop_server(process,stream)
    process,stream = start_server('postgres-http-restarted.txt')
    try:
        with httpx.Client(base_url=base) as client:
            token = expect(client.post('/auth/login',json={'email':email,'password':'FictionalPass!123'}),200)['token']
            client.headers['Authorization'] = f'Bearer {token}'
            persisted = expect(client.get(f'/bookings/{bid}'),200)
            history_after = expect(client.get(f'/bookings/{bid}/history'),200)
            assert persisted['status']=='CANCELLED' and history_before==history_after
            assert [e['event_type'] for e in history_after]==['BOOKING_SUBMITTED','BOOKING_RESCHEDULED','BOOKING_CANCELLED']
            assert all(e['actor_user_id']==user['id'] and datetime.fromisoformat(e['created_at']).tzinfo for e in history_after)
    finally:
        stop_server(process,stream)
    runtime_engine = create_engine(runtime)
    with runtime_engine.connect() as conn:
        role = conn.execute(text("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user")).one()
        assert tuple(role)==('petops_runtime',False,False,False)
        assert not conn.execute(text("SELECT has_table_privilege(current_user,'booking_events','DELETE')")).scalar_one()
        assert not conn.execute(text("SELECT has_table_privilege(current_user,'booking_events','UPDATE')")).scalar_one()
        assert not conn.execute(text("SELECT has_table_privilege(current_user,'booking_events','TRUNCATE')")).scalar_one()
        assert not conn.execute(text("SELECT has_table_privilege(current_user,'alembic_version','UPDATE')")).scalar_one()
        assert not conn.execute(text("SELECT has_table_privilege(current_user,'services','UPDATE')")).scalar_one()
        assert not conn.execute(text("SELECT has_table_privilege(current_user,'users','UPDATE')")).scalar_one()
        assert conn.execute(text('SELECT count(*) FROM bookings WHERE id=:id'),{'id':uuid.UUID(bid)}).scalar_one()==1
    summary = {'postgresql_version':version,'initial_public_tables':initial_tables,'revision':'0002',
               'http_server_processes':2,'runtime_role':role[0],'runtime_superuser':False,
               'persisted_booking_id':bid,'persisted_status':persisted['status'],
               'history_events':len(history_after),'history_equal_after_process_restart':True,
               'history_actor_and_timezone_verified':True,'runtime_history_update_delete_truncate_denied':True,
               'runtime_migration_metadata_service_and_user_updates_denied':True}
    summary_name = 'postgres-runtime-recheck.json' if runtime_only else 'postgres-runtime.json'
    (EVIDENCE/summary_name).write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('Real HTTP process restart + PostgreSQL booking/history persistence PASS',flush=True)
    if not runtime_only:
        run(['-m','pytest','-q','--tb=short'],config['test_url'],'postgres-tests.txt',{'PETOPS_TEST_DATABASE_URL':config['test_url']})
    runtime_engine.dispose(); engine.dispose()


if __name__ == '__main__':
    main()
