"""Boarding acceptance/RBAC/integrity and actual PostgreSQL race executions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_engine
from app.main import app
from app.models import (Accommodation, BoardingAllocation, BoardingNote, BoardingStay,
    Booking, BookingEvent, User)
from app.services import business_today
from tests.conftest import login, register_customer
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case, boarding, grooming, allocate, assign, confirm


@pytest.fixture
def stay(case):
    c=case;c['b']=boarding(c,start=business_today());allocate(c,c['b'])
    now=datetime.now(timezone.utc)
    assign(c,c['b'])
    confirm(c,c['b']);c['staff']=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    c['other_staff']=bearer(login(c['client'],c['seed']['staff2'].email,'DemoPass!123'))
    return c


def act(c,action,body=None,headers=None,expected=200,bid=None):
    r=c['client'].post(f"/boarding/bookings/{bid or c['b']['id']}/{action}",headers=headers or c['staff'],json=body if body is not None else {})
    assert r.status_code==expected,r.text
    return r


def through(c,stop='check-out',headers=None):
    result=None
    for action in ('check-in','check-out'):
        result=act(c,action,headers=headers).json()
        if action==stop:break
    return result


def snapshot(c):
    with SessionLocal() as db:
        b=db.get(Booking,uuid.UUID(c['b']['id']))
        return (b.status.value,b.version,*[db.scalar(select(func.count()).select_from(t)) for t in (BoardingStay,BoardingNote,BookingEvent)],
            db.scalar(select(func.count()).select_from(BoardingAllocation).where(BoardingAllocation.released_at.is_(None))))


def test_boarding_end_to_end_linked_history_and_release(stay):
    c=stay;admitted=act(c,'check-in').json();s=admitted['boarding_stay']
    assert s['booking_id']==c['b']['id'] and admitted['allocation_history'][-1]['released_at'] is None
    act(c,'start-stay',expected=409);act(c,'complete',expected=409)
    n1=act(c,'notes',{'note':' Fictional arrival observation. '},expected=201).json()
    n2=act(c,'notes',{'note':'Fictional stay observation.'},expected=201).json()
    out=act(c,'check-out').json();done=out
    assert done['booking']['status']=='COMPLETED' and done['booking']['pet_id']==c['pet']
    assert done['booking']['assigned_staff_user_id']==str(c['seed']['staff1'].id)
    assert [n['note'] for n in done['stay_notes']]==['Fictional arrival observation.','Fictional stay observation.']
    assert done['allocation_history'][-1]['released_at']==out['boarding_stay']['checked_out_at']
    times=[datetime.fromisoformat(done['boarding_stay'][step+'_at']) for step in ('checked_in','stay_started','checked_out','completed')]
    assert times==sorted(times) and all(t.tzinfo for t in times)
    assert all(done['boarding_stay'][step+'_by_user_id']==str(c['seed']['staff1'].id) for step in ('checked_in','stay_started','checked_out','completed'))
    assert len(done['history'])==9
    assert admitted['booking']['status']=='STAYING'
    assert s['checked_in_at']==s['stay_started_at']
    assert s['checked_in_by_user_id']==s['stay_started_by_user_id']
    assert done['boarding_stay']['checked_out_at']==done['boarding_stay']['completed_at']
    for note in (n1,n2):
        event=next(e for e in done['history'] if e['details'] and e['details'].get('boarding_note_id')==note['id'])
        assert event['created_at']==note['created_at'] and event['actor_user_id']==note['actor_user_id']
    assert c['client'].get(f"/boarding/bookings/{c['b']['id']}",headers=c['owner']).json()==done
    assert c['client'].get(f"/bookings/{c['b']['id']}/history",headers=c['owner']).json()==done['history']


def test_boarding_without_staff_is_admin_operated(case):
    c=case;c['b']=boarding(c,start=business_today());allocate(c,c['b']);confirm(c,c['b'])
    c['staff']=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    act(c,'check-in',expected=404)
    assert through(c,headers=c['admin'])['boarding_stay']['completed_by_user_id']==str(c['seed']['admin'].id)


def test_all_new_protected_endpoints_reject_anonymous(stay):
    c=stay;c['client'].cookies.clear();before=snapshot(c);base=f"/boarding/bookings/{c['b']['id']}"
    for path in ('/boarding/bookings','/boarding/staff-options',base):assert c['client'].get(path).status_code==401
    for path,body in [(base+'/'+a,{}) for a in ('check-in','start-stay','check-out','complete')]+[(base+'/notes',{'note':'Denied'})]:
        assert c['client'].post(path,json=body).status_code==401
    assert snapshot(c)==before


@pytest.mark.parametrize('who,code',[('owner',403),('other_staff',404)])
def test_prohibited_operators_cannot_mutate(stay,who,code):
    before=snapshot(stay)
    for action in ('check-in','start-stay','check-out','complete','notes'):
        act(stay,action,{'note':'Denied'} if action=='notes' else {},headers=stay[who],expected=code)
    assert snapshot(stay)==before


def test_work_is_scoped_and_customer_visible(stay):
    c=stay;register_customer(c['client'],'separate.boarding@petops.example','Separate Customer')
    other=bearer(login(c['client'],'separate.boarding@petops.example','CustomerPass!123'))
    for headers in (other,c['other_staff']):
        assert c['client'].get('/boarding/bookings',headers=headers).json()==[]
        assert c['client'].get(f"/boarding/bookings/{c['b']['id']}",headers=headers).status_code==404
    for who in ('owner','staff','admin'):
        d=c['client'].get(f"/boarding/bookings/{c['b']['id']}",headers=c[who]).json()
        assert d['pet_name']=='Milo' and d['customer_name']=='Customer One' and d['allocation_history']
        assert 'password_hash' not in str(d)
    for who in ('owner','staff','other_staff'):
        assert c['client'].get('/boarding/staff-options',headers=c[who]).status_code==403
    assert c['client'].get('/boarding/staff-options',headers=c['admin']).status_code==200


def test_reassignment_and_inactive_staff_denials(stay):
    c=stay;now=datetime.now(timezone.utc)
    assign(c,c['b'],staff=c['seed']['staff2'].id)
    act(c,'check-in',expected=404)
    with SessionLocal() as db:db.get(User,c['seed']['staff1'].id).is_active=False;db.commit()
    act(c,'check-in',expected=401)
    act(c,'check-in',headers=c['other_staff'])


def test_invalid_transitions_and_repeated_actions(stay):
    c=stay
    for action in ('start-stay','check-out','complete','notes'):
        act(c,action,{'note':'Denied'} if action=='notes' else {},expected=409)
    for action in ('check-in','check-out'):
        act(c,action);before=snapshot(c);act(c,action,expected=409);assert snapshot(c)==before
    act(c,'notes',{'note':'Too late'},expected=409)


@pytest.mark.parametrize('state',['SUBMITTED','REJECTED','CANCELLED'])
def test_unconfirmed_boarding_cannot_check_in(case,state):
    c=case;c['b']=boarding(c,start=business_today())
    if state=='REJECTED':assert c['client'].post(f"/admin/bookings/{c['b']['id']}/status",headers=c['admin'],json={'status':state}).status_code==200
    if state=='CANCELLED':assert c['client'].post(f"/bookings/{c['b']['id']}/cancel",headers=c['owner']).status_code==200
    act(c,'check-in',headers=c['admin'],expected=409)


def test_grooming_cannot_enter_boarding(case):
    c=case;c['b']=grooming(c)
    for action in ('check-in','start-stay','check-out','complete','notes'):
        act(c,action,{'note':'Wrong workflow'} if action=='notes' else {},headers=c['admin'],expected=404)
    assert c['client'].get('/boarding/bookings',headers=c['admin']).json()==[]


def test_checkin_future_reservation_denied(case):
    c=case;c['b']=boarding(c);allocate(c,c['b']);confirm(c,c['b'])
    act(c,'check-in',headers=c['admin'],expected=409)
    assert snapshot(c)[0]=='CONFIRMED'


@pytest.mark.parametrize('body',[{}, {'note':''},{'note':'   '},{'note':'x'*4001},{'note':'a\x00b'},{'note':7},{'note':'ok','actor_user_id':str(uuid.uuid4())},{'note':'ok','created_at':'2026-01-01T00:00:00Z'}])
def test_invalid_or_spoofed_note_rolls_back(stay,body):
    act(stay,'check-in');before=snapshot(stay);act(stay,'notes',body,expected=422);assert snapshot(stay)==before


@pytest.mark.parametrize('note',['x','é'*4000])
def test_valid_note_boundaries(stay,note):
    act(stay,'check-in');assert act(stay,'notes',{'note':note},expected=201).json()['note']==note


def test_operation_cannot_spoof_actor_or_time(stay):
    before=snapshot(stay);act(stay,'check-in',{'checked_in_at':datetime.now(timezone.utc).isoformat(),'checked_in_by_user_id':str(stay['seed']['admin'].id)},expected=422);assert snapshot(stay)==before


def test_changes_and_allocations_locked_after_checkin(stay):
    c=stay
    for action in ('check-in','check-out'):
        act(c,action);before=snapshot(c)
        assert c['client'].post(f"/bookings/{c['b']['id']}/cancel",headers=c['owner']).status_code==409
        assert c['client'].post(f"/bookings/{c['b']['id']}/reschedule",headers=c['owner'],json={'boarding_start':c['day'].isoformat(),'boarding_end':(c['day']+timedelta(days=3)).isoformat()}).status_code==409
        allocate(c,c['b'],expected=409)
        assert c['client'].put(f"/admin/bookings/{c['b']['id']}/staff",headers=c['admin'],json={'staff_user_id':None}).status_code==409
        assert snapshot(c)==before


def test_reschedule_requires_new_allocation_confirmation(case):
    c=case;c['b']=boarding(c);allocate(c,c['b']);confirm(c,c['b'])
    assert c['client'].post(f"/bookings/{c['b']['id']}/reschedule",headers=c['owner'],json={'boarding_start':business_today().isoformat(),'boarding_end':(business_today()+timedelta(days=2)).isoformat()}).status_code==200
    act(c,'check-in',headers=c['admin'],expected=409);confirm(c,c['b'],expected=409)
    allocate(c,c['b']);confirm(c,c['b']);done=through(c,headers=c['admin'])
    assert len(done['allocation_history'])==2 and all(a['released_at'] for a in done['allocation_history'])
    assert any(e['event_type']=='BOOKING_RESCHEDULED' and e['old_schedule']!=e['new_schedule'] for e in done['history'])


@pytest.mark.parametrize('target',['CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED'])
def test_sql_state_without_stay_is_denied(stay,target):
    before=snapshot(stay)
    with pytest.raises(IntegrityError),SessionLocal() as db:
        db.execute(text('UPDATE bookings SET status=:target WHERE id=:id'),{'target':target,'id':uuid.UUID(stay['b']['id'])});db.commit()
    assert snapshot(stay)==before


@pytest.mark.parametrize('defect',['customer_actor','unassigned_actor','future_time','wrong_allocation'])
def test_sql_checkin_actor_time_allocation_guards(stay,defect):
    c=stay;bid=uuid.UUID(c['b']['id']);before=snapshot(c)
    with SessionLocal() as db:
        b=db.get(Booking,bid)
        a=db.scalar(select(BoardingAllocation).where(BoardingAllocation.booking_id==bid,BoardingAllocation.released_at.is_(None)))
        actor=b.created_by_user_id if defect=='customer_actor' else c['seed']['staff2'].id if defect=='unassigned_actor' else c['seed']['staff1'].id
        when=datetime.now(timezone.utc)+(timedelta(days=1) if defect=='future_time' else timedelta())
        db.execute(text("UPDATE bookings SET status='STAYING' WHERE id=:id"),{'id':bid})
        with pytest.raises(IntegrityError):
            db.execute(text('INSERT INTO boarding_stays(id,booking_id,allocation_id,checked_in_by_user_id,checked_in_at,stay_started_by_user_id,stay_started_at) VALUES (:s,:b,:a,:actor,:at,:actor,:at)'),{'s':uuid.uuid4(),'b':bid,'a':uuid.uuid4() if defect=='wrong_allocation' else a.id,'actor':actor,'at':when})
        db.rollback()
    assert snapshot(c)==before


def test_sql_duplicate_stay_and_checkout_without_release_denied(stay):
    c=stay;act(c,'check-in');bid=uuid.UUID(c['b']['id'])
    with SessionLocal() as db:
        s=db.scalar(select(BoardingStay).where(BoardingStay.booking_id==bid))
        with pytest.raises(IntegrityError) as failure:
            db.execute(text('INSERT INTO boarding_stays(id,booking_id,allocation_id,checked_in_by_user_id,checked_in_at,stay_started_by_user_id,stay_started_at) VALUES (:id,:b,:a,:actor,statement_timestamp(),:actor,statement_timestamp())'),{'id':uuid.uuid4(),'b':bid,'a':s.allocation_id,'actor':c['seed']['staff1'].id})
        assert failure.value.orig.sqlstate=='23505';db.rollback()
    before=snapshot(c);now=datetime.now(timezone.utc)
    with pytest.raises(IntegrityError),SessionLocal() as db:
        db.execute(text("UPDATE bookings SET status='COMPLETED' WHERE id=:b"),{'b':bid})
        db.execute(text('UPDATE boarding_stays SET checked_out_at=:at,checked_out_by_user_id=:actor,completed_at=:at,completed_by_user_id=:actor WHERE booking_id=:b'),{'b':bid,'at':now,'actor':c['seed']['staff1'].id})
        db.execute(text("INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:id,:b,'BOARDING_CHECKED_OUT','STAYING','COMPLETED',:actor,:at)"),{'id':uuid.uuid4(),'b':bid,'actor':c['seed']['staff1'].id,'at':now})
        db.execute(text("INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:id,:b,'BOARDING_COMPLETED','STAYING','COMPLETED',:actor,:at)"),{'id':uuid.uuid4(),'b':bid,'actor':c['seed']['staff1'].id,'at':now})
        db.commit()
    assert snapshot(c)==before


@pytest.mark.parametrize('statement',[
    "UPDATE boarding_allocations SET released_at=statement_timestamp(),released_by_user_id=:actor WHERE booking_id=:id AND released_at IS NULL",
    "UPDATE bookings SET status='SUBMITTED' WHERE id=:id",
    "UPDATE bookings SET boarding_end=boarding_end+1 WHERE id=:id",
    "UPDATE bookings SET assigned_staff_user_id=NULL,staff_start=NULL,staff_end=NULL WHERE id=:id",
])
def test_sql_active_stay_cannot_lose_resources_or_links(stay,statement):
    act(stay,'check-in');before=snapshot(stay)
    with pytest.raises(IntegrityError),SessionLocal() as db:
        db.execute(text(statement),{'id':uuid.UUID(stay['b']['id']),'actor':stay['seed']['admin'].id});db.commit()
    assert snapshot(stay)==before


@pytest.mark.parametrize('statement',[
    "UPDATE boarding_stays SET completed_at=completed_at+interval '1 second' WHERE booking_id=:id",
    "DELETE FROM boarding_stays WHERE booking_id=:id",
    "UPDATE boarding_notes SET note='changed' WHERE stay_id=(SELECT id FROM boarding_stays WHERE booking_id=:id)",
    "DELETE FROM boarding_notes WHERE stay_id=(SELECT id FROM boarding_stays WHERE booking_id=:id)",
    "DELETE FROM booking_events WHERE booking_id=:id AND event_type='BOARDING_CHECKED_IN'",
    "DELETE FROM bookings WHERE id=:id",
    "DELETE FROM boarding_allocations WHERE booking_id=:id",
])
def test_sql_completed_history_is_retained(stay,statement):
    act(stay,'check-in');act(stay,'notes',{'note':'Fictional retained note'},expected=201)
    for action in ('check-out',):act(stay,action)
    before=snapshot(stay)
    with pytest.raises(IntegrityError),SessionLocal() as db:
        db.execute(text(statement),{'id':uuid.UUID(stay['b']['id'])});db.commit()
    assert snapshot(stay)==before


def test_note_event_mismatch_rolls_back(stay,monkeypatch):
    import app.boarding_routes as routes
    act(stay,'check-in');before=snapshot(stay);original=routes.BookingEvent
    def mismatch(**kwargs):kwargs['created_at']-=timedelta(seconds=1);return original(**kwargs)
    monkeypatch.setattr(routes,'BookingEvent',mismatch)
    act(stay,'notes',{'note':'Fictional update'},expected=409);assert snapshot(stay)==before


def test_allocation_release_failure_rolls_back_checkout(stay,monkeypatch):
    import app.boarding_routes as routes
    through(stay,'check-in');before=snapshot(stay);original=routes.add_event
    def mismatch(*args,**kwargs):kwargs['created_at']-=timedelta(seconds=1);return original(*args,**kwargs)
    monkeypatch.setattr(routes,'add_event',mismatch)
    act(stay,'check-out',expected=409);assert snapshot(stay)==before


def overdue_fixture(c,offset=2):
    """Synthetic historical fixture only: disable/re-enable date guard as DB owner.

    All other lifecycle/capacity/FK/event constraints run, including deferred
    checks before restoring the guard. Runtime has no DDL/owner privileges.
    """
    ids={k:uuid.uuid4() for k in ('b','a','s','start_event','stay_event')};day=business_today();now=datetime.now(timezone.utc)-timedelta(days=offset)
    with SessionLocal() as db:
        original=db.get(Booking,uuid.UUID(c['b']['id']))
        args={**ids,'customer':original.customer_id,'pet':original.pet_id,'service':original.service_id,'owner':original.created_by_user_id,
            'admin':c['seed']['admin'].id,'unit':c['seed']['unit'].id,'lo':day-timedelta(days=offset),'hi':day-timedelta(days=offset-1),'at':now,'created':now-timedelta(hours=1)}
        db.execute(text('ALTER TABLE boarding_stays DISABLE TRIGGER guard_boarding_stay'))
        db.execute(text("INSERT INTO bookings(id,customer_id,pet_id,service_id,booking_type,status,boarding_start,boarding_end,created_by_user_id,created_at,updated_at) VALUES (:b,:customer,:pet,:service,'BOARDING','SUBMITTED',:lo,:hi,:owner,:created,:created)"),args)
        db.execute(text('INSERT INTO boarding_allocations(id,booking_id,accommodation_id,starts_on,ends_on,created_by_user_id,created_at) VALUES (:a,:b,:unit,:lo,:hi,:admin,:created)'),args)
        for state in ('CONFIRMED','STAYING'):db.execute(text('UPDATE bookings SET status=:state WHERE id=:b'),{**args,'state':state})
        db.execute(text('INSERT INTO boarding_stays(id,booking_id,allocation_id,checked_in_by_user_id,checked_in_at,stay_started_by_user_id,stay_started_at) VALUES (:s,:b,:a,:admin,:at,:admin,:at)'),args)
        db.execute(text("INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:start_event,:b,'BOARDING_CHECKED_IN','CONFIRMED','STAYING',:admin,:at)"),args)
        db.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        db.execute(text('ALTER TABLE boarding_stays ENABLE TRIGGER guard_boarding_stay'));db.commit()
        assert db.execute(text("SELECT tgenabled FROM pg_trigger WHERE tgname='guard_boarding_stay'")).scalar_one()=='O'
    return str(ids['b'])


def test_overdue_stay_still_occupies_place_until_checkout(case):
    c=case;c['b']=boarding(c,start=business_today());allocate(c,c['b']);confirm(c,c['b'])
    with SessionLocal() as db:db.get(Accommodation,c['seed']['unit'].id).capacity=1;db.commit()
    old=overdue_fixture(c)
    act(c,'check-in',headers=c['admin'],expected=409)
    act(c,'check-out',headers=c['admin'],bid=old)
    assert act(c,'check-in',headers=c['admin']).json()['booking']['status']=='STAYING'


def test_capacity_reduction_cannot_ignore_overdue_physical_occupancy(case):
    c=case;c['b']=boarding(c,start=business_today());allocate(c,c['b']);confirm(c,c['b'])
    with SessionLocal() as db:db.get(Accommodation,c['seed']['unit'].id).capacity=2;db.commit()
    overdue_fixture(c,2);overdue_fixture(c,4)
    with pytest.raises(IntegrityError),SessionLocal() as db:
        db.get(Accommodation,c['seed']['unit'].id).capacity=1;db.commit()


def race_fixture(c):
    c['b']=boarding(c,start=business_today());allocate(c,c['b']);confirm(c,c['b'])
    other=boarding(c,start=business_today());allocate(c,other);confirm(c,other)
    with SessionLocal() as db:db.get(Accommodation,c['seed']['unit'].id).capacity=2;db.commit()
    overdue_fixture(c)
    return [c['b']['id'],other['id']]


def test_physical_checkin_race_has_only_one_remaining_place(case):
    c=case;bids=race_fixture(c);barrier=Barrier(2)
    def request(bid):
        with TestClient(app) as client:
            barrier.wait(timeout=15);return client.post(f'/boarding/bookings/{bid}/check-in',headers=c['admin'],json={}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(request,bids))
    assert sorted(results)==[200,409],results
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(BoardingStay).where(BoardingStay.checked_out_at.is_(None)))==2


@pytest.mark.parametrize('isolation',['READ COMMITTED','REPEATABLE READ'])
def test_sql_physical_capacity_race(case,isolation):
    c=case;bids=race_fixture(c);barrier=Barrier(2)
    def reserve(bid):
        with Session(get_engine().execution_options(isolation_level=isolation)) as db:
            try:
                a=db.scalar(select(BoardingAllocation).where(BoardingAllocation.booking_id==uuid.UUID(bid),BoardingAllocation.released_at.is_(None)))
                barrier.wait(timeout=15);now=datetime.now(timezone.utc)
                db.execute(text("UPDATE bookings SET status='STAYING' WHERE id=:id"),{'id':uuid.UUID(bid)})
                db.execute(text('INSERT INTO boarding_stays(id,booking_id,allocation_id,checked_in_by_user_id,checked_in_at,stay_started_by_user_id,stay_started_at) VALUES (:s,:b,:a,:actor,:now,:actor,:now)'),{'s':uuid.uuid4(),'b':uuid.UUID(bid),'a':a.id,'actor':c['seed']['admin'].id,'now':now})
                db.execute(text("INSERT INTO booking_events(id,booking_id,event_type,old_status,new_status,actor_user_id,created_at) VALUES (:id,:b,'BOARDING_CHECKED_IN','CONFIRMED','STAYING',:actor,:now)"),{'id':uuid.uuid4(),'b':uuid.UUID(bid),'actor':c['seed']['admin'].id,'now':now})
                db.commit();return 'ok'
            except (IntegrityError,OperationalError) as exc:
                db.rollback();assert getattr(exc.orig,'sqlstate',None) in {'23514','40001','40P01'};return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,bids))
    assert sorted(results)==['denied','ok'],results


def test_duplicate_boarding_operation_races(stay):
    c=stay
    for action in ('check-in','check-out'):
        barrier=Barrier(2)
        def request(_):
            with TestClient(app) as client:
                barrier.wait(timeout=15);return client.post(f"/boarding/bookings/{c['b']['id']}/{action}",headers=c['staff'],json={}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(request,range(2)))
        assert sorted(results)==[200,409],results
    with SessionLocal() as db:assert db.scalar(select(func.count()).select_from(BoardingStay))==1


def test_note_checkout_race_is_atomic(stay):
    c=stay;through(c,'check-in');barrier=Barrier(2)
    def request(action):
        with TestClient(app) as client:
            barrier.wait(timeout=15)
            return client.post(f"/boarding/bookings/{c['b']['id']}/{action}",headers=c['staff'],json={'note':'Fictional race note'} if action=='notes' else {}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:note,checkout=list(pool.map(request,['notes','check-out']))
    assert checkout==200 and note in {201,409}
    data=c['client'].get(f"/boarding/bookings/{c['b']['id']}",headers=c['owner']).json()
    assert len(data['stay_notes'])==int(note==201)
    if data['stay_notes']:assert data['stay_notes'][0]['created_at']<=data['boarding_stay']['checked_out_at']
