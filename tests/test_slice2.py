"""Slice 2 acceptance, security, raw-SQL integrity and real PG race cases."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
import uuid

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_engine
from app.models import (Accommodation, BoardingAllocation, Booking, BookingEvent, BookingStatus,
                        StaffAvailability, User, utcnow)
from app.services import business_today
from tests.conftest import login
from tests.test_vertical_slice import bearer, make_customer_with_pet


@pytest.fixture
def case(client, seed_base):
    token, pet = make_customer_with_pet(client)
    admin = login(client, seed_base['admin'].email, 'DemoPass!123')
    return {'client':client, 'seed':seed_base, 'owner':bearer(token), 'admin':bearer(admin), 'pet':pet,
            'start':(datetime.now(timezone.utc)+timedelta(days=5)).replace(hour=10,minute=0,second=0,microsecond=0),
            'day':business_today()+timedelta(days=2)}


def grooming(c, start=None, expected=201):
    r=c['client'].post('/bookings',headers=c['owner'],json={'pet_id':c['pet'],
        'service_id':str(c['seed']['grooming'].id),'grooming_start':(start or c['start']).isoformat()})
    assert r.status_code==expected,r.text
    return r.json()


def boarding(c, start=None, end=None, expected=201):
    start=start or c['day']; end=end or start+timedelta(days=2)
    r=c['client'].post('/bookings',headers=c['owner'],json={'pet_id':c['pet'],
        'service_id':str(c['seed']['boarding'].id),'boarding_start':start.isoformat(),'boarding_end':end.isoformat()})
    assert r.status_code==expected,r.text
    return r.json()


def assign(c,b,staff=None,expected=200,**window):
    r=c['client'].put(f"/admin/bookings/{b['id']}/staff",headers=c['admin'],json={
        'staff_user_id':str(staff or c['seed']['staff1'].id),**window})
    assert r.status_code==expected,r.text
    return r


def allocate(c,b,unit=None,expected=200):
    r=c['client'].put(f"/admin/bookings/{b['id']}/accommodation",headers=c['admin'],json={
        'accommodation_id':str(unit or c['seed']['unit'].id)})
    assert r.status_code==expected,r.text
    return r


def confirm(c,b,expected=200):
    r=c['client'].post(f"/admin/bookings/{b['id']}/status",headers=c['admin'],json={'status':'CONFIRMED'})
    assert r.status_code==expected,r.text
    return r


def history(c,b):
    return c['client'].get(f"/bookings/{b['id']}/history",headers=c['owner']).json()


def configure_unit(c,capacity=1,is_active=True,expected=200):
    r=c['client'].put(f"/admin/accommodations/{c['seed']['unit'].id}",headers=c['admin'],json={
        'name':'Fictional Test Unit','category':'Fictional','capacity':capacity,'is_active':is_active})
    assert r.status_code==expected,r.text
    return r


def only_staff_window(c,start,end,gap=False):
    # PS-01: legacy windows are inert; this helper also isolates one operational Staff.
    with SessionLocal() as db:
        db.execute(update(StaffAvailability).values(is_active=False))
        db.get(User,c['seed']['staff2'].id).is_active=False
        db.add(StaffAvailability(staff_user_id=c['seed']['staff1'].id,starts_at=start,ends_at=end,
                                 is_active=True,updated_by_user_id=c['seed']['admin'].id))
        db.commit()


@pytest.mark.parametrize('value,expected',[(1,200),(60,200),(0,422),(-1,422),(1.5,422),(True,422),(2147483648,422)])
def test_duration_configuration_boundaries(case,value,expected):
    c=case
    r=c['client'].put(f"/admin/services/{c['seed']['grooming'].id}/duration",headers=c['admin'],json={'duration_minutes':value})
    assert r.status_code==expected
    if expected==200:
        b=grooming(c)
        assert b['grooming_duration_minutes']==value
        result=assign(c,b).json()
        assert datetime.fromisoformat(result['ends_at'])-datetime.fromisoformat(result['starts_at'])==timedelta(minutes=value)
        confirm(c,b)


def test_missing_duration_fails_closed_and_boarding_rejects_duration(case):
    c=case
    with SessionLocal() as db:
        db.get(__import__('app.models',fromlist=['Service']).Service,c['seed']['grooming'].id).duration_minutes=None
        db.commit()
    grooming(c,expected=409)
    assert c['client'].put(f"/admin/services/{c['seed']['boarding'].id}/duration",headers=c['admin'],json={'duration_minutes':60}).status_code==422


def test_duration_snapshot_and_future_configuration(case):
    c=case; b=grooming(c)
    assert c['client'].put(f"/admin/services/{c['seed']['grooming'].id}/duration",headers=c['admin'],json={'duration_minutes':90}).status_code==200
    assign(c,b); confirm(c,b)
    assert c['client'].get(f"/bookings/{b['id']}",headers=c['owner']).json()['grooming_duration_minutes']==60
    r=c['client'].post(f"/bookings/{b['id']}/reschedule",headers=c['owner'],json={'grooming_start':(c['start']+timedelta(days=1)).isoformat()})
    assert r.status_code==200 and r.json()['grooming_duration_minutes']==90
    event=history(c,b)[-1]
    assert event['old_schedule']['grooming_duration_minutes']==60 and event['new_schedule']['grooming_duration_minutes']==90


def test_adjacent_windows_jointly_cover_and_assignments_may_touch(case):
    c=case; t=c['start']
    only_staff_window(c,t,t+timedelta(minutes=30))
    with SessionLocal() as db:
        db.add(StaffAvailability(staff_user_id=c['seed']['staff1'].id,starts_at=t+timedelta(minutes=30),
            ends_at=t+timedelta(hours=2),is_active=True,updated_by_user_id=c['seed']['admin'].id)); db.commit()
    a=grooming(c,t); overlapping=grooming(c,t+timedelta(minutes=30)); touching=grooming(c,t+timedelta(hours=1))
    assign(c,a); assign(c,overlapping,expected=409); assign(c,touching)
    confirm(c,a); confirm(c,touching)


@pytest.mark.parametrize('reason',['gap','too_short','inactive'])
def test_full_duration_and_active_staff_are_required(case,reason):
    c=case; t=c['start']
    only_staff_window(c,t,t+timedelta(minutes=30 if reason!='inactive' else 60))
    with SessionLocal() as db:
        if reason=='gap':
            db.add(StaffAvailability(staff_user_id=c['seed']['staff1'].id,starts_at=t+timedelta(minutes=31),
                ends_at=t+timedelta(hours=2),is_active=True,updated_by_user_id=c['seed']['admin'].id))
        if reason=='inactive': db.get(User,c['seed']['staff1'].id).is_active=False
        db.commit()
    r=c['client'].post('/availability',headers=c['owner'],json={'service_id':str(c['seed']['grooming'].id),'grooming_start':t.isoformat()})
    assert r.status_code==200 and r.json()['available'] is (reason!='inactive')
    grooming(c,expected=409 if reason=='inactive' else 201)


def test_grooming_confirmation_requires_assignment_and_rechecks_it(case):
    c=case; b=grooming(c)
    confirm(c,b,409)
    assign(c,b); confirm(c,b)
    assert history(c,b)[-1]['new_status']=='CONFIRMED'
    assert history(c,b)[-1]['actor_user_id']==str(c['seed']['admin'].id)
    assert c['client'].put(f"/admin/bookings/{b['id']}/staff",headers=c['admin'],json={'staff_user_id':None}).status_code==409


def test_reassignment_changes_staff_access_and_keeps_history(case):
    c=case; b=grooming(c); assign(c,b); confirm(c,b)
    assign(c,b,c['seed']['staff2'].id)
    first=login(c['client'],c['seed']['staff1'].email,'DemoPass!123')
    second=login(c['client'],c['seed']['staff2'].email,'DemoPass!123')
    assert c['client'].get(f"/staff/bookings/{b['id']}",headers=bearer(first)).status_code==404
    assert c['client'].get(f"/staff/bookings/{b['id']}",headers=bearer(second)).status_code==200
    e=history(c,b)[-1]
    assert e['old_assigned_staff_user_id']==str(c['seed']['staff1'].id)
    assert e['new_assigned_staff_user_id']==str(c['seed']['staff2'].id)
    assert e['details']['old_work']['starts_at']==b['grooming_start']


def test_boarding_peak_capacity_not_sum_of_partial_overlaps(case):
    c=case; configure_unit(c,2); day=c['day']
    a=boarding(c,day,day+timedelta(days=1)); b=boarding(c,day+timedelta(days=1),day+timedelta(days=2))
    allocate(c,a); allocate(c,b)
    whole=boarding(c,day,day+timedelta(days=2)); allocate(c,whole)
    for booking in (a,b,whole): confirm(c,booking)
    r=c['client'].post('/admin/boarding-availability',headers=c['admin'],json={
        'service_id':str(c['seed']['boarding'].id),'boarding_start':day.isoformat(),'boarding_end':(day+timedelta(days=2)).isoformat()})
    assert r.status_code==200 and r.json()[0]['peak_occupancy']==2 and r.json()[0]['available_places']==0


def test_full_boarding_capacity_blocks_submission_allocation_and_confirmation(case):
    c=case; configure_unit(c,1)
    a=boarding(c); b=boarding(c)
    allocate(c,a); confirm(c,a)
    boarding(c,expected=409); allocate(c,b,expected=409); confirm(c,b,409)
    assert not history(c,b)[-1]['new_status']=='CONFIRMED'


def test_inactive_accommodation_is_not_available(case):
    c=case; b=boarding(c)
    configure_unit(c,1,False)
    boarding(c,expected=409); allocate(c,b,expected=409); confirm(c,b,409)


@pytest.mark.parametrize('capacity',[0,-1,1.5,True,2147483648])
def test_invalid_capacity_rejected(case,capacity):
    c=case; configure_unit(c,capacity,expected=422)


def test_capacity_reduction_and_deactivation_cannot_invalidate_allocations(case):
    c=case; configure_unit(c,2)
    a=boarding(c); b=boarding(c); allocate(c,a); allocate(c,b)
    configure_unit(c,1,expected=409); configure_unit(c,2,False,409)


def test_admin_reallocation_retains_old_row_and_staff_can_only_view(case):
    c=case; b=boarding(c)
    first=allocate(c,b).json(); confirm(c,b)
    unit=c['client'].post('/admin/accommodations',headers=c['admin'],json={
        'name':'Second Fictional Unit','category':'Fictional','capacity':1,'notes':'Fictional suitability note'}).json()
    second=allocate(c,b,uuid.UUID(unit['id'])).json()
    start=datetime.combine(c['day'],datetime.min.time(),timezone.utc)
    assign(c,b,starts_at=start.isoformat(),ends_at=(start+timedelta(hours=1)).isoformat())
    staff=login(c['client'],c['seed']['staff1'].email,'DemoPass!123')
    response=c['client'].get(f"/staff/bookings/{b['id']}",headers=bearer(staff))
    assert response.status_code==200 and response.json()['accommodation_allocations'][0]['id']==second['id']
    assert c['client'].put(f"/admin/bookings/{b['id']}/accommodation",headers=bearer(staff),json={'accommodation_id':unit['id']}).status_code==403
    with SessionLocal() as db:
        old=db.get(BoardingAllocation,uuid.UUID(first['id']))
        assert old.released_at and old.released_by_user_id==c['seed']['admin'].id
        assert db.scalar(select(func.count()).select_from(BoardingAllocation).where(BoardingAllocation.booking_id==uuid.UUID(b['id'])))==2
    e=[e for e in history(c,b) if e['event_type']=='ACCOMMODATION_REALLOCATED'][-1]
    assert e['details']['old_allocations'][0]['id']==first['id'] and e['details']['new_allocation']['id']==second['id']


def test_boarding_staff_optional_and_initial_period_is_derived(case):
    c=case; b=boarding(c); allocate(c,b); confirm(c,b)
    assign(c,b)
    outside=datetime.combine(c['day']-timedelta(days=2),datetime.min.time(),timezone.utc)
    assign(c,b,expected=422,starts_at=outside.isoformat(),ends_at=(outside+timedelta(hours=1)).isoformat())
    inside=datetime.combine(c['day'],datetime.min.time(),timezone.utc)
    assign(c,b,expected=422,starts_at=inside.isoformat(),ends_at=(inside+timedelta(hours=1)).isoformat())
    r=c['client'].put(f"/admin/bookings/{b['id']}/staff",headers=c['admin'],json={'staff_user_id':None})
    assert r.status_code==200


def test_reschedule_grooming_rejects_conflict_then_requires_reassignment(case):
    c=case; t=c['start']; only_staff_window(c,t,t+timedelta(hours=3))
    a=grooming(c,t); b=grooming(c,t+timedelta(hours=1)); assign(c,a); assign(c,b); confirm(c,a)
    old=history(c,a)
    url=f"/bookings/{a['id']}/reschedule"
    assert c['client'].post(url,headers=c['owner'],json={'grooming_start':(t+timedelta(minutes=30)).isoformat()}).status_code==409
    assert history(c,a)==old
    r=c['client'].post(url,headers=c['owner'],json={'grooming_start':(t+timedelta(hours=2)).isoformat()})
    assert r.status_code==200 and r.json()['status']=='SUBMITTED' and r.json()['assigned_staff_user_id'] is None
    assert history(c,a)[-1]['details']['released_resources']['staff_user_id']==str(c['seed']['staff1'].id)
    confirm(c,a,409); assign(c,r.json()); confirm(c,a)


def test_reschedule_boarding_revalidates_excludes_own_reservation_and_releases_history(case):
    c=case; configure_unit(c,1); day=c['day']
    a=boarding(c); b=boarding(c,day+timedelta(days=4),day+timedelta(days=6))
    original=allocate(c,a).json(); allocate(c,b); confirm(c,a)
    before=history(c,a); url=f"/bookings/{a['id']}/reschedule"
    bad={'boarding_start':b['boarding_start'],'boarding_end':b['boarding_end']}
    assert c['client'].post(url,headers=c['owner'],json=bad).status_code==409
    assert history(c,a)==before
    good={'boarding_start':(day+timedelta(days=1)).isoformat(),'boarding_end':(day+timedelta(days=3)).isoformat()}
    r=c['client'].post(url,headers=c['owner'],json=good)
    assert r.status_code==200 and r.json()['status']=='SUBMITTED'
    with SessionLocal() as db:
        row=db.get(BoardingAllocation,uuid.UUID(original['id']))
        assert row.released_at is not None and row.starts_on==day
    confirm(c,a,409); allocate(c,a); confirm(c,a)
    e=[e for e in history(c,a) if e['event_type']=='BOOKING_RESCHEDULED'][-1]
    assert e['details']['released_resources']['allocations'][0]['id']==original['id']


def test_new_endpoints_reject_anonymous_and_wrong_roles(case):
    c=case; b=boarding(c); staff=login(c['client'],c['seed']['staff1'].email,'DemoPass!123')
    requests=[('PUT',f"/admin/services/{c['seed']['grooming'].id}/duration",{'duration_minutes':60}),
      ('POST',f"/admin/staff/{c['seed']['staff1'].id}/availability",{'starts_at':c['start'].isoformat(),'ends_at':(c['start']+timedelta(hours=2)).isoformat()}),
      ('GET',f"/admin/staff/{c['seed']['staff1'].id}/availability",None),
      ('POST','/admin/accommodations',{'name':'Blocked','category':'Fictional','capacity':1}),
      ('GET','/admin/accommodations',None),
      ('PUT',f"/admin/accommodations/{c['seed']['unit'].id}",{'name':'Blocked','category':'Fictional','capacity':1}),
      ('PUT',f"/admin/bookings/{b['id']}/staff",{'staff_user_id':str(c['seed']['staff1'].id)}),
      ('PUT',f"/admin/bookings/{b['id']}/accommodation",{'accommodation_id':str(c['seed']['unit'].id)}),
      ('POST','/admin/boarding-availability',{'service_id':str(c['seed']['boarding'].id),'boarding_start':c['day'].isoformat(),'boarding_end':(c['day']+timedelta(days=1)).isoformat()})]
    with SessionLocal() as db:
        window=db.scalar(select(StaffAvailability).where(StaffAvailability.staff_user_id==c['seed']['staff1'].id))
        requests.append(('PUT',f"/admin/staff/{c['seed']['staff1'].id}/availability/{window.id}",{'starts_at':c['start'].isoformat(),'ends_at':(c['start']+timedelta(hours=2)).isoformat()}))
    for headers in (c['owner'],bearer(staff)):
        for method,path,body in requests:
            assert c['client'].request(method,path,headers=headers,json=body).status_code==403,(method,path)
    c['client'].cookies.clear()
    for method,path,body in requests+[('GET','/staff/availability',None),('POST','/availability',{'service_id':str(c['seed']['grooming'].id),'grooming_start':c['start'].isoformat()})]:
        assert c['client'].request(method,path,json=body).status_code==401,(method,path)


@pytest.fixture
def postgres_only():
    if get_engine().dialect.name!='postgresql': pytest.skip('PostgreSQL trigger/exclusion/concurrency guarantee')


@pytest.mark.parametrize('kind',['GROOMING','BOARDING'])
def test_database_confirmation_bypass_denied(case,postgres_only,kind):
    c=case; b=grooming(c) if kind=='GROOMING' else boarding(c)
    with SessionLocal() as db:
        db.get(Booking,uuid.UUID(b['id'])).status=BookingStatus.CONFIRMED
        with pytest.raises(IntegrityError,match='BR-002'): db.commit()
        db.rollback()


@pytest.mark.parametrize('defect',['window','duration','missing_window','unavailable'])
def test_database_assignment_and_duration_bypass_denied(case,postgres_only,defect):
    c=case; b=grooming(c)
    with SessionLocal() as db:
        row=db.get(Booking,uuid.UUID(b['id'])); row.assigned_staff_user_id=c['seed']['staff1'].id
        row.staff_start=c['start']; row.staff_end=c['start']+timedelta(hours=1)
        if defect=='window': row.staff_end+=timedelta(minutes=1)
        elif defect=='duration': row.grooming_duration_minutes=61
        elif defect=='missing_window': row.staff_start=row.staff_end=None
        elif defect=='unavailable':
            db.execute(update(StaffAvailability).where(StaffAvailability.staff_user_id==c['seed']['staff1'].id).values(is_active=False))
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


def test_database_capacity_and_history_bypasses_denied(case,postgres_only):
    c=case; configure_unit(c,1); a=boarding(c); b=boarding(c); allocation=allocate(c,a).json(); confirm(c,a)
    with SessionLocal() as db:
        db.add(BoardingAllocation(booking_id=uuid.UUID(b['id']),accommodation_id=c['seed']['unit'].id,
            starts_on=c['day'],ends_on=c['day']+timedelta(days=2),created_by_user_id=c['seed']['admin'].id))
        with pytest.raises(IntegrityError,match='capacity exceeded'): db.commit()
        db.rollback()
        row=db.get(BoardingAllocation,uuid.UUID(allocation['id']))
        row.released_at=utcnow(); row.released_by_user_id=c['seed']['admin'].id
        with pytest.raises(IntegrityError,match='BR-002'): db.commit()
        db.rollback()
        row=db.get(BoardingAllocation,uuid.UUID(allocation['id']))
        row.ends_on+=timedelta(days=1)
        with pytest.raises(IntegrityError,match='immutable'): db.commit()
        db.rollback()
        db.delete(db.get(BoardingAllocation,uuid.UUID(allocation['id'])))
        with pytest.raises(IntegrityError,match='cannot be deleted'): db.commit()
        db.rollback()


@pytest.mark.parametrize('defect',['grooming','wrong_dates','staff_actor','inactive_unit'])
def test_database_allocation_type_dates_actor_and_active_guards(case,postgres_only,defect):
    c=case; b=grooming(c) if defect=='grooming' else boarding(c)
    with SessionLocal() as db:
        if defect=='inactive_unit':
            db.get(Accommodation,c['seed']['unit'].id).is_active=False; db.commit()
        db.add(BoardingAllocation(booking_id=uuid.UUID(b['id']),accommodation_id=c['seed']['unit'].id,
            starts_on=c['day']+timedelta(days=1 if defect=='wrong_dates' else 0),ends_on=c['day']+timedelta(days=2),
            created_by_user_id=c['seed']['staff1' if defect=='staff_actor' else 'admin'].id))
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


def test_database_availability_and_account_changes_cannot_break_assigned_work(case,postgres_only):
    c=case; b=grooming(c); assign(c,b)
    with SessionLocal() as db:
        window=db.scalar(select(StaffAvailability).where(StaffAvailability.staff_user_id==c['seed']['staff1'].id))
        window.is_active=False
        db.commit() # PS-01: old windows no longer determine eligibility
        db.get(User,c['seed']['staff1'].id).is_active=False
        with pytest.raises(IntegrityError,match='deactivating Staff'): db.commit()
        db.rollback()


def concurrent_attempts(actions,isolation='READ COMMITTED'):
    gate=Barrier(len(actions))
    def worker(action):
        with Session(get_engine().execution_options(isolation_level=isolation)) as db:
            db.execute(text("SET LOCAL statement_timeout='15s'"))
            db.execute(text("SELECT count(*) FROM boarding_allocations"))  # establish snapshots
            action(db)
            gate.wait(timeout=10)
            try:
                db.commit(); return 'committed'
            except (IntegrityError,OperationalError) as exc:
                db.rollback()
                assert getattr(exc.orig,'sqlstate',None) in {'23514','23P01','40001','40P01'}
                return 'rejected'
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        futures=[pool.submit(worker,action) for action in actions]
        return sorted(f.result(timeout=25) for f in futures)


def test_database_assignment_without_responsibility_history_is_rejected(case,postgres_only):
    c=case;b=grooming(c)
    with SessionLocal() as db:
        row=db.get(Booking,uuid.UUID(b['id']));row.assigned_staff_user_id=c['seed']['staff1'].id;row.staff_start=c['start'];row.staff_end=c['start']+timedelta(hours=1)
        with pytest.raises(IntegrityError,match='latest responsibility'):db.commit()
        db.rollback()
    # Concurrent API-level assignment remains exercised by test_product_simplification.


@pytest.mark.parametrize('isolation',['READ COMMITTED','REPEATABLE READ'])
def test_concurrent_capacity_allocation_only_one_wins(case,postgres_only,isolation):
    c=case; configure_unit(c,1); a=boarding(c); b=boarding(c)
    def action(bid):
        def allocate_row(db):
            db.add(BoardingAllocation(booking_id=uuid.UUID(bid),accommodation_id=c['seed']['unit'].id,
                starts_on=c['day'],ends_on=c['day']+timedelta(days=2),created_by_user_id=c['seed']['admin'].id))
        return allocate_row
    assert concurrent_attempts([action(a['id']),action(b['id'])],isolation)==['committed','rejected']
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BoardingAllocation).where(BoardingAllocation.released_at.is_(None)))==1


def test_availability_retired_but_legacy_admin_read_preserved(case):
    c=case;sid=c['seed']['staff1'].id;t=c['start'];body={'starts_at':t.isoformat(),'ends_at':(t+timedelta(hours=1)).isoformat()}
    assert c['client'].post(f'/admin/staff/{sid}/availability',headers=c['admin'],json=body).status_code==410
    rows=c['client'].get(f'/admin/staff/{sid}/availability',headers=c['admin']);assert rows.status_code==200 and rows.json()
    staff=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    assert c['client'].get('/staff/availability',headers=staff).status_code==410
    assert c['client'].get('/staff/availability',headers=c['owner']).status_code==403


@pytest.mark.parametrize('defect',['zero','naive','not_staff'])
def test_availability_configuration_invalid_cases(case,defect):
    c=case; t=c['start']; staff=c['seed']['admin' if defect=='not_staff' else 'staff1'].id
    payload={'starts_at':t.isoformat(),'ends_at':(t+timedelta(hours=1)).isoformat()}
    if defect=='zero': payload['ends_at']=payload['starts_at']
    if defect=='naive': payload['starts_at']=t.replace(tzinfo=None).isoformat()
    r=c['client'].post(f'/admin/staff/{staff}/availability',headers=c['admin'],json=payload)
    assert r.status_code==(410 if defect=='not_staff' else 422)


def test_staff_deactivated_after_request_cannot_be_assigned(case):
    c=case; b=grooming(c)
    with SessionLocal() as db:
        db.get(User,c['seed']['staff1'].id).is_active=False; db.commit()
    before=history(c,b)
    assign(c,b,expected=409)
    assert history(c,b)==before
    assign(c,b,c['seed']['staff2'].id); confirm(c,b)


@pytest.mark.parametrize('defect',['capacity','inactive','schedule'])
def test_database_configuration_and_stale_allocation_guards(case,postgres_only,defect):
    c=case; configure_unit(c,2); a=boarding(c); b=boarding(c); allocate(c,a); allocate(c,b)
    with SessionLocal() as db:
        if defect=='capacity': db.get(Accommodation,c['seed']['unit'].id).capacity=1
        elif defect=='inactive': db.get(Accommodation,c['seed']['unit'].id).is_active=False
        else: db.get(Booking,uuid.UUID(a['id'])).boarding_end+=timedelta(days=1)
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


def test_legacy_window_change_does_not_prevent_booking_assignment(case,postgres_only):
    c=case;b=grooming(c)
    with SessionLocal() as db:
        db.execute(update(StaffAvailability).values(is_active=False));db.commit()
    assign(c,b);confirm(c,b)


def test_legacy_unknown_assignment_fails_closed_for_new_work(case,postgres_only):
    c=case; old=grooming(c); pending=grooming(c,c['start']+timedelta(days=1)); assign(c,old)
    # Privileged migration-style fixture only: represent an existing 0002 link
    # with no recorded work window. The runtime role cannot ALTER triggers.
    with SessionLocal() as db:
        db.execute(text('ALTER TABLE bookings DISABLE TRIGGER guard_booking_resources'))
        db.execute(update(Booking).where(Booking.id==uuid.UUID(old['id'])).values(staff_start=None,staff_end=None))
        db.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))  # drain events before ALTER
        db.execute(text('ALTER TABLE bookings ENABLE TRIGGER guard_booking_resources'))
        db.get(User,c['seed']['staff2'].id).is_active=False
        db.commit()
    grooming(c,c['start']+timedelta(days=2),expected=409)
    assign(c,pending,expected=409)
    with SessionLocal() as db:
        row=db.get(Booking,uuid.UUID(pending['id'])); row.assigned_staff_user_id=c['seed']['staff1'].id
        row.staff_start=c['start']+timedelta(days=1); row.staff_end=row.staff_start+timedelta(hours=1)
        with pytest.raises(IntegrityError,match='legacy assigned work'): db.commit()
        db.rollback()


@pytest.mark.parametrize('field',['name','category','notes'])
def test_resource_text_rejects_postgresql_nul_character(case,field):
    c=case; payload={'name':'Safe Fictional Unit','category':'Fictional','capacity':1,'notes':'Safe'}
    payload[field]='invalid\x00text'
    assert c['client'].post('/admin/accommodations',headers=c['admin'],json=payload).status_code==422


def test_grooming_end_overflow_is_validation_error(case):
    c=case
    grooming(c,datetime(9999,12,31,23,59,tzinfo=timezone.utc),expected=422)
