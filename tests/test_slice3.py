"""Actual Grooming workflow, authorization, database integrity and duplicate races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.main import app
from app.models import Booking, BookingEvent, BookingStatus, GroomingRecord, User
from tests.conftest import login, register_customer
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case, grooming, boarding, assign


@pytest.fixture
def work(case):
    c = case
    b = grooming(c)
    assign(c, b)
    assert c['client'].post(f"/admin/bookings/{b['id']}/status", headers=c['admin'], json={'status':'CONFIRMED'}).status_code == 200
    c['b'] = b
    c['staff'] = bearer(login(c['client'], c['seed']['staff1'].email, 'DemoPass!123'))
    c['other_staff'] = bearer(login(c['client'], c['seed']['staff2'].email, 'DemoPass!123'))
    return c


def operation(c, op, body=None, headers=None, expected=200):
    r = c['client'].post(f"/grooming/bookings/{c['b']['id']}/{op}", json=body or {}, headers=headers or c['staff'])
    assert r.status_code == expected, r.text
    return r


def snapshot(c):
    with SessionLocal() as db:
        b = db.get(Booking, uuid.UUID(c['b']['id']))
        r = db.scalar(select(GroomingRecord).where(GroomingRecord.booking_id == b.id))
        return (b.status.value, b.version, r.completed_at if r else None,
                db.scalar(select(func.count()).select_from(BookingEvent)),
                db.scalar(select(func.count()).select_from(GroomingRecord)))


def test_grooming_end_to_end_linked_history(work):
    c=work; started=operation(c,'start').json()
    assert started['booking']['status']=='IN_PROGRESS'
    completed=operation(c,'complete',{'service_notes':'  Fictional wash and trim completed.  '}).json()
    b,r=completed['booking'],completed['grooming_record']
    assert b['status']=='COMPLETED' and b['pet_id']==c['pet'] and b['service_id']==str(c['seed']['grooming'].id)
    assert r['booking_id']==b['id'] and r['service_notes']=='Fictional wash and trim completed.'
    assert r['started_by_user_id']==r['completed_by_user_id']==str(c['seed']['staff1'].id)
    assert datetime.fromisoformat(r['completed_at']) >= datetime.fromisoformat(r['started_at'])
    assert datetime.fromisoformat(r['started_at']).tzinfo is not None
    events=completed['history']; assert [e['event_type'] for e in events][-2:]==['GROOMING_STARTED','GROOMING_COMPLETED']
    assert events[-2]['created_at']==r['started_at'] and events[-1]['created_at']==r['completed_at']
    assert completed==c['client'].get(f"/grooming/bookings/{b['id']}",headers=c['owner']).json()
    assert c['client'].get(f"/bookings/{b['id']}",headers=c['owner']).json()['status']=='COMPLETED'
    assert c['client'].get(f"/bookings/{b['id']}/history",headers=c['owner']).json()==events
    assert c['client'].get('/grooming/bookings',headers=c['owner']).json()[0]['status']=='COMPLETED'


def test_admin_can_complete_assigned_staff_work(work):
    operation(work,'start')
    r=operation(work,'complete',headers=work['admin']).json()['grooming_record']
    assert r['started_by_user_id']==str(work['seed']['staff1'].id)
    assert r['completed_by_user_id']==str(work['seed']['admin'].id)


def test_admin_can_start_and_complete(work):
    operation(work,'start',headers=work['admin']); operation(work,'complete',headers=work['admin'])


def test_new_routes_reject_anonymous(work):
    c=work; c['client'].cookies.clear(); before=snapshot(c); base=f"/grooming/bookings/{c['b']['id']}"
    for method,path,body in [('GET','/grooming/bookings',None),('GET',base,None),('GET',base+'/eligible-staff',None),('POST',base+'/start',{}),('POST',base+'/complete',{}),('POST','/auth/logout',None)]:
        assert c['client'].request(method,path,json=body).status_code==401
    assert snapshot(c)==before


@pytest.mark.parametrize('who,expected',[('owner',403),('other_staff',404)])
def test_prohibited_operators_do_not_mutate(work,who,expected):
    before=snapshot(work)
    for op in ('start','complete'): operation(work,op,headers=work[who],expected=expected)
    assert snapshot(work)==before


def test_scoped_worklist_details_and_candidates(work):
    c=work; bid=c['b']['id']
    register_customer(c['client'],'separate.demo@petops.example','Separate Customer')
    other=bearer(login(c['client'],'separate.demo@petops.example','CustomerPass!123'))
    for headers in (other,c['other_staff']):
        assert c['client'].get('/grooming/bookings',headers=headers).json()==[]
        assert c['client'].get(f'/grooming/bookings/{bid}',headers=headers).status_code==404
    for headers in (c['owner'],c['staff']):
        assert c['client'].get(f'/grooming/bookings/{bid}/eligible-staff',headers=headers).status_code==403
        detail=c['client'].get(f'/grooming/bookings/{bid}',headers=headers).json()
        assert detail['pet_name']=='Milo' and detail['customer_name']=='Customer One'
        assert 'password' not in str(detail).lower()
    assert c['client'].get('/grooming/bookings',headers=c['staff']).json()[0]['id']==bid


def test_reassignment_revokes_old_staff_work_access(work):
    c=work;assign(c,c['b'],staff=c['seed']['staff2'].id)
    assert c['client'].get('/grooming/bookings',headers=c['staff']).json()==[]
    operation(c,'start',expected=404)
    operation(c,'start',headers=c['other_staff'])


def test_deactivated_staff_cannot_operate(work):
    # Unassigned inactive account: existing guard forbids deactivating active assigned Staff.
    with SessionLocal() as db:
        db.get(User,work['seed']['staff2'].id).is_active=False;db.commit()
    operation(work,'start',headers=work['other_staff'],expected=401)


def test_only_valid_transitions_and_no_repeat(work):
    c=work;operation(c,'complete',expected=409);operation(c,'start')
    before=snapshot(c);operation(c,'start',expected=409);assert snapshot(c)==before
    operation(c,'complete');before=snapshot(c)
    for op in ('start','complete'): operation(c,op,expected=409)
    assert snapshot(c)==before


@pytest.mark.parametrize('state',['SUBMITTED','REJECTED','CANCELLED'])
def test_unconfirmed_or_closed_cannot_start(case,state):
    c=case;c['b']=grooming(c)
    if state=='REJECTED': assert c['client'].post(f"/admin/bookings/{c['b']['id']}/status",headers=c['admin'],json={'status':state}).status_code==200
    if state=='CANCELLED': assert c['client'].post(f"/bookings/{c['b']['id']}/cancel",headers=c['owner']).status_code==200
    operation(c,'start',headers=c['admin'],expected=409)


def test_boarding_does_not_enter_grooming(case):
    c=case;c['b']=boarding(c)
    for op in ('start','complete'): operation(c,op,headers=c['admin'],expected=404)
    assert c['client'].get('/grooming/bookings',headers=c['admin']).json()==[]


@pytest.mark.parametrize('notes',[None,'x','é'*4000])
def test_completion_note_valid_boundaries(work,notes):
    operation(work,'start');assert operation(work,'complete',{'service_notes':notes}).json()['grooming_record']['service_notes']==notes


@pytest.mark.parametrize('body',[{'service_notes':''},{'service_notes':'   '},{'service_notes':'x'*4001},{'service_notes':'a\x00b'},{'service_notes':7},{'completed_by_user_id':str(uuid.uuid4())},{'completed_at':'2026-01-01T00:00:00Z'}])
def test_completion_rejects_invalid_or_spoofed_data(work,body):
    operation(work,'start');before=snapshot(work);operation(work,'complete',body,expected=422);assert snapshot(work)==before


def test_start_rejects_spoofed_actor_or_time(work):
    before=snapshot(work)
    operation(work,'start',{'started_by_user_id':str(work['seed']['admin'].id),'started_at':datetime.now(timezone.utc).isoformat()},expected=422)
    assert snapshot(work)==before


def test_operations_block_changes_and_assignment_then_preserve_history(work):
    c=work;operation(c,'start')
    for completed in (False,True):
        if completed: operation(c,'complete')
        before=snapshot(c);bid=c['b']['id']
        assert c['client'].post(f'/bookings/{bid}/cancel',headers=c['owner']).status_code==409
        assert c['client'].post(f'/bookings/{bid}/reschedule',headers=c['owner'],json={'grooming_start':(c['start']+timedelta(days=1)).isoformat()}).status_code==409
        assign(c,c['b'],staff=c['seed']['staff2'].id,expected=409)
        assert c['client'].get(f'/grooming/bookings/{bid}/eligible-staff',headers=c['admin']).status_code==409
        assert snapshot(c)==before


def test_reschedule_reconfirmation_is_required_before_work(work):
    c=work;bid=c['b']['id']
    assert c['client'].post(f'/bookings/{bid}/reschedule',headers=c['owner'],json={'grooming_start':(c['start']+timedelta(days=1)).isoformat()}).status_code==200
    operation(c,'start',expected=404) # old Staff loses access after reschedule.
    operation(c,'start',headers=c['admin'],expected=409)
    assign(c,c['b']);assert c['client'].post(f'/admin/bookings/{bid}/status',headers=c['admin'],json={'status':'CONFIRMED'}).status_code==200
    operation(c,'start');data=operation(c,'complete').json()
    assert any(e['event_type']=='BOOKING_RESCHEDULED' and e['old_schedule']!=e['new_schedule'] for e in data['history'])


def test_completed_reservation_releases_capacity_without_deleting_links(work):
    c=work;operation(c,'start');operation(c,'complete')
    new=grooming(c);assign(c,new)
    assert c['client'].get(f"/grooming/bookings/{c['b']['id']}",headers=c['owner']).json()['grooming_record']['completed_at']


@pytest.mark.parametrize('statement',[
    "UPDATE bookings SET status='COMPLETED' WHERE id=:id",
    "UPDATE bookings SET status='IN_PROGRESS' WHERE id=:id",
])
def test_sql_cannot_bypass_record_event_workflow(work,statement):
    before=snapshot(work)
    with pytest.raises(IntegrityError), SessionLocal() as db:
        db.execute(text(statement),{'id':uuid.UUID(work['b']['id'])});db.commit()
    assert snapshot(work)==before


@pytest.mark.parametrize('defect',['customer_actor','unassigned_actor','future_start','before_booking'])
def test_sql_start_actor_and_time_are_validated_immediately(work,defect):
    c=work;bid=uuid.UUID(c['b']['id']);before=snapshot(c)
    with SessionLocal() as db:
        b=db.get(Booking,bid)
        actor=b.created_by_user_id if defect=='customer_actor' else c['seed']['staff2'].id if defect=='unassigned_actor' else c['seed']['staff1'].id
        started=datetime.now(timezone.utc)+timedelta(days=1) if defect=='future_start' else b.created_at-timedelta(seconds=1) if defect=='before_booking' else datetime.now(timezone.utc)
        db.execute(text("UPDATE bookings SET status='IN_PROGRESS' WHERE id=:id"),{'id':bid})
        with pytest.raises(IntegrityError):
            db.execute(text('INSERT INTO grooming_records(id,booking_id,started_by_user_id,started_at) VALUES (:record,:id,:actor,:started)'),{'record':uuid.uuid4(),'id':bid,'actor':actor,'started':started})
        db.rollback()
    assert snapshot(c)==before


def test_sql_duplicate_record_and_invalid_completion_time(work):
    c=work;operation(c,'start');bid=uuid.UUID(c['b']['id']);before=snapshot(c)
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text('INSERT INTO grooming_records(id,booking_id,started_by_user_id,started_at) VALUES (:record,:id,:actor,statement_timestamp())'),{'record':uuid.uuid4(),'id':bid,'actor':c['seed']['staff1'].id})
        db.rollback()
        db.execute(text("UPDATE bookings SET status='COMPLETED' WHERE id=:id"),{'id':bid})
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE grooming_records SET completed_at=started_at-interval '1 second',completed_by_user_id=:actor WHERE booking_id=:id"),{'id':bid,'actor':c['seed']['staff1'].id})
        db.rollback()
    assert snapshot(c)==before


@pytest.mark.parametrize('statement',[
    "UPDATE grooming_records SET service_notes='changed' WHERE booking_id=:id",
    "DELETE FROM grooming_records WHERE booking_id=:id",
    "UPDATE booking_events SET actor_user_id=:actor WHERE booking_id=:id AND event_type='GROOMING_COMPLETED'",
    "DELETE FROM booking_events WHERE booking_id=:id AND event_type='GROOMING_STARTED'",
    "UPDATE bookings SET status='SUBMITTED' WHERE id=:id",
    "UPDATE bookings SET grooming_start=grooming_start+interval '1 day' WHERE id=:id",
    "UPDATE bookings SET assigned_staff_user_id=NULL WHERE id=:id",
    "DELETE FROM bookings WHERE id=:id",
])
def test_completed_sql_history_is_preserved(work,statement):
    operation(work,'start');operation(work,'complete',{'service_notes':'Fictional completion'})
    before=snapshot(work)
    with pytest.raises(IntegrityError), SessionLocal() as db:
        db.execute(text(statement),{'id':uuid.UUID(work['b']['id']),'actor':work['seed']['admin'].id});db.commit()
    assert snapshot(work)==before


def test_failed_event_integrity_rolls_back_completion(work,monkeypatch):
    import app.grooming_routes as routes
    operation(work,'start');before=snapshot(work);original=routes.add_event
    def mismatch(*args,**kwargs):
        kwargs['created_at']=kwargs['created_at']+timedelta(seconds=1)
        original(*args,**kwargs)
    monkeypatch.setattr(routes,'add_event',mismatch)
    operation(work,'complete',expected=409)
    assert snapshot(work)==before


def test_duplicate_start_and_complete_races(work):
    c=work
    def race(op):
        barrier=Barrier(2)
        def request(_):
            with TestClient(app) as client:
                barrier.wait(timeout=10)
                return client.post(f"/grooming/bookings/{c['b']['id']}/{op}",headers=c['staff'],json={}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(request,range(2)))
        assert sorted(results)==[200,409],results
    race('start');race('complete')
    assert snapshot(c)[-1]==1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.event_type.in_(['GROOMING_STARTED','GROOMING_COMPLETED'])))==2


def test_logout_revokes_token_and_cookie(work):
    client=work['client'];assert client.post('/auth/logout',headers=work['staff']).status_code==204
    assert client.get('/me',headers=work['staff']).status_code==401
    assert client.get('/me').status_code==401
