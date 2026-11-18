"""Genuine final integration/security/validation gaps; prior suites retained."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from threading import Event
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,text

from app.database import SessionLocal
from app.main import app
from app.models import BookingEvent,Notification
from app.services import business_today
from tests.conftest import login,register_customer
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case,grooming,boarding,assign,allocate,confirm
from tests.test_slice5 import call,inbox,kinds,settings,sweep,report


@pytest.mark.parametrize('instant',['9999-12-31T23:59:59-14:00','0001-01-01T00:00:00+14:00'])
def test_unrepresentable_utc_booking_is_validation_error(case,instant):
    c=case;before=inbox(c)
    call(c,'POST','/bookings',{'pet_id':c['pet'],'service_id':str(c['seed']['grooming'].id),'grooming_start':instant},who='owner',code=422)
    assert inbox(c)==before and call(c,'GET','/bookings',who='owner')==[]


@pytest.mark.parametrize('surface',['window','assignment','availability','reschedule'])
def test_unrepresentable_utc_other_surfaces_fail_closed(case,surface):
    c=case;instant='9999-12-31T23:58:59-14:00';b=grooming(c)
    if surface=='window':
        call(c,'POST',f"/admin/staff/{c['seed']['staff1'].id}/availability",{'starts_at':instant,'ends_at':'9999-12-31T23:59:59-14:00'},code=422)
    elif surface=='assignment':
        bb=boarding(c);call(c,'PUT',f"/admin/bookings/{bb['id']}/staff",{'staff_user_id':str(c['seed']['staff1'].id),'starts_at':instant,'ends_at':'9999-12-31T23:59:59-14:00'},code=422)
    elif surface=='availability':
        call(c,'POST','/availability',{'service_id':str(c['seed']['grooming'].id),'grooming_start':instant},who='owner',code=422)
    else:
        call(c,'POST',f"/bookings/{b['id']}/reschedule",{'grooming_start':instant},who='owner',code=422)
    assert call(c,'GET',f"/bookings/{b['id']}",who='owner')['status']=='SUBMITTED'


def test_password_reset_cannot_leave_concurrent_old_password_login_valid(case,monkeypatch):
    import app.main as main
    c=case;verified=Event();release=Event();original=main.issue_session;staff=c['seed']['staff2']
    def paused(db,user):
        if user.id==staff.id:
            verified.set();assert release.wait(12),'Test synchronization timed out'
        return original(db,user)
    monkeypatch.setattr(main,'issue_session',paused)
    def authenticate():
        with TestClient(app) as client:return client.post('/auth/login',json={'email':staff.email,'password':'DemoPass!123'})
    def reset():
        with TestClient(app) as client:return client.put('/admin/staff/'+str(staff.id),headers=c['admin'],json={'email':staff.email,'is_active':True,'password':'FinalReset!123'})
    with ThreadPoolExecutor(2) as pool:
        pending=pool.submit(authenticate);assert verified.wait(8)
        resetting=pool.submit(reset)
        try:
            # Observe either reset completion or actual database lock wait; avoid
            # assuming a timing threshold proves serialization.
            deadline=time.monotonic()+8;observed=False
            while time.monotonic()<deadline:
                if resetting.done():observed=True;break
                with SessionLocal() as db:
                    blocked=db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND wait_event_type='Lock' AND query LIKE '%FROM users%' AND query LIKE '%FOR UPDATE%')"))
                if blocked:observed=True;break
                time.sleep(.02)
            assert observed,'Neither reset completion nor database lock wait observed'
        finally:release.set()
        auth=pending.result(timeout=10);changed=resetting.result(timeout=10)
    assert auth.status_code==changed.status_code==200
    token=auth.json()['token']
    authenticated=c['client'].get('/me',headers=bearer(token))
    assert authenticated.status_code==401
    assert c['client'].post('/auth/login',json={'email':staff.email,'password':'DemoPass!123'}).status_code==401
    fresh=login(c['client'],staff.email,'FinalReset!123')
    assert c['client'].get('/me',headers=bearer(fresh)).status_code==200


@pytest.mark.parametrize('body',[b'{',b'[]',b'null',b'"text"',b'{"name":123}',b'{"name":"\xff"}'])
def test_malformed_pet_requests_are_client_errors_without_writes(case,body):
    c=case;before=call(c,'GET','/pets',who='owner')
    r=c['client'].post('/pets',headers={**c['owner'],'Content-Type':'application/json'},content=body)
    assert r.status_code in (400,422)
    assert call(c,'GET','/pets',who='owner')==before


@pytest.mark.parametrize('kind',['GROOMING','BOARDING'])
def test_integrated_customer_to_completion_notifications_and_admin_review(case,kind):
    c=case;call(c,'PUT','/customer/profile',{'display_name':'Fictional Integrated Customer'},who='owner')
    call(c,'PUT','/pets/'+c['pet'],{'name':'Fictional Integrated Pet'},who='owner')
    if kind=='GROOMING':
        schedule={'service_id':str(c['seed']['grooming'].id),'grooming_start':c['start'].isoformat()}
    else:
        schedule={'service_id':str(c['seed']['boarding'].id),'boarding_start':business_today().isoformat(),'boarding_end':(business_today()+timedelta(days=2)).isoformat()}
    assert call(c,'POST','/availability',schedule,who='owner')['available']
    b=call(c,'POST','/bookings',{**schedule,'pet_id':c['pet']},who='owner',code=201)
    if kind=='GROOMING':assign(c,b)
    else:allocate(c,b)
    confirm(c,b)
    new=({'grooming_start':(c['start']+timedelta(days=1)).isoformat()} if kind=='GROOMING' else {'boarding_start':business_today().isoformat(),'boarding_end':(business_today()+timedelta(days=3)).isoformat()})
    call(c,'POST',f"/bookings/{b['id']}/reschedule",new,who='owner')
    confirm(c,b,expected=409)
    if kind=='GROOMING':assign(c,b)
    else:allocate(c,b)
    confirm(c,b)
    c['staff']=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    if kind=='GROOMING':
        call(c,'POST',f"/grooming/bookings/{b['id']}/start",{},who='staff')
        completed=call(c,'POST',f"/grooming/bookings/{b['id']}/complete",{'service_notes':'Fictional integrated Grooming outcome'},who='staff')
    else:
        # Optional Staff inherits the Boarding stay; accommodation stays Admin-only.
        now=datetime.now(timezone.utc)
        assign(c,b)
        for action in ('check-in',):
            call(c,'POST',f"/boarding/bookings/{b['id']}/{action}",{},who='staff')
        call(c,'POST',f"/boarding/bookings/{b['id']}/notes",{'note':'Fictional integrated stay observation'},who='staff',code=201)
        completed=call(c,'POST',f"/boarding/bookings/{b['id']}/check-out",{},who='staff')
    assert completed['booking']['status']=='COMPLETED'
    assert completed['customer_name']=='Fictional Integrated Customer' and completed['pet_name']=='Fictional Integrated Pet'
    from tests.revamp_views import as_owner_sees, core, owner_history  # 2026-11-18 D4 contract
    assert core(call(c,'GET',f"/{kind.lower()}/bookings/{b['id']}",who='owner'))==as_owner_sees(completed)
    assert core(call(c,'GET',f"/admin/bookings/{b['id']}/history"))==core(completed)
    assert call(c,'GET',f"/bookings/{b['id']}/history",who='owner')==owner_history(completed['history'])
    assert all(e['actor_user_id'] and e['created_at'] for e in completed['history'])
    assert kinds(c)==['BOOKING_SUBMITTED','BOOKING_CONFIRMED','BOOKING_RESCHEDULED','BOOKING_RECONFIRMED']
    d=report(c);assert d['total_bookings']==1 and d['completed_services_by_type'][kind]==1 and d['bookings_by_status']['COMPLETED']==1
    assert d['booking_change_events']['BOOKING_RESCHEDULED']==1 and d['boarding_current']['physically_occupied']==0
    assert d['upcoming_arrivals']['total']==d['upcoming_departures']['total']==0
    # Cross-Customer/assigned-work boundary remains through the whole joined flow.
    register_customer(c['client'],'integrated.other@petops.example','Fictional Other')
    c['other']=bearer(login(c['client'],'integrated.other@petops.example','CustomerPass!123'))
    for path in (f'/bookings/{b["id"]}',f'/bookings/{b["id"]}/history',f'/{kind.lower()}/bookings/{b["id"]}'):
        call(c,'GET',path,who='other',code=404)
    n=inbox(c)[0];call(c,'GET','/notifications/'+n['id'],who='other',code=404)
    call(c,'POST',f"/bookings/{b['id']}/cancel",who='owner',code=409)


def test_repeat_notice_read_and_admin_sweep_reject_spoofed_payload(case):
    c=case;b=grooming(c);n=inbox(c)[0]
    for payload in ({'recipient_user_id':str(uuid.uuid4())},{'actor_user_id':str(c['seed']['admin'].id)},{'kind':'BOOKING_CONFIRMED'}):
        call(c,'POST','/notifications/'+n['id']+'/read',payload,who='owner',code=422)
        call(c,'POST','/admin/reminders/run',payload,code=422)
    assert inbox(c)[0]['read_at'] is None


def test_dashboard_creation_boundary_and_independent_completion_period(case):
    from app.management import period_bounds
    from app.models import Booking,Customer
    c=case;day=business_today();lo,_=period_bounds(day,day)
    # Explicit synthetic prior-created record, one microsecond before local
    # midnight. No elapsed-day or real business activity is claimed.
    with SessionLocal() as db:
        owner=db.scalar(select(Customer))
        b=Booking(customer_id=owner.id,pet_id=uuid.UUID(c['pet']),service_id=c['seed']['grooming'].id,
            booking_type='GROOMING',status='SUBMITTED',grooming_start=c['start'],grooming_duration_minutes=60,
            created_by_user_id=owner.user_id,created_at=lo-timedelta(microseconds=1))
        db.add(b);db.flush();db.add(BookingEvent(booking_id=b.id,event_type='BOOKING_SUBMITTED',new_status='SUBMITTED',actor_user_id=owner.user_id));db.commit();bid=str(b.id)
    assign(c,{'id':bid});confirm(c,{'id':bid})
    call(c,'POST',f'/grooming/bookings/{bid}/start',{})
    call(c,'POST',f'/grooming/bookings/{bid}/complete',{})
    today=report(c);yesterday=report(c,day-timedelta(days=1),day-timedelta(days=1))
    assert today['total_bookings']==0 and today['completed_services_by_type']['GROOMING']==1
    assert yesterday['total_bookings']==1 and yesterday['bookings_by_status']['COMPLETED']==1
    assert yesterday['completed_services_by_type']['GROOMING']==0
