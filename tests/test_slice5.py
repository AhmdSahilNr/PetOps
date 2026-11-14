"""Slice 5 acceptance/security/integrity and real PostgreSQL reminder races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,datetime,timedelta,timezone
from threading import Barrier
import uuid

import pytest
from sqlalchemy import func,select,text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal,get_engine
from app.models import (Booking,BookingEvent,Customer,ManagementEvent,Notification,
    NotificationSetting,Role,Service,User)
from app.notifications import generate_due_reminders
from app.services import business_today
from tests.conftest import login,register_customer
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case,grooming,boarding,assign,allocate,confirm
from tests.test_slice4 import stay,act,through


def call(c,method,path,body=None,who='admin',code=200):
    r=c['client'].request(method,path,headers=c[who],**({'json':body} if body is not None else {}))
    assert r.status_code==code,r.text
    return r.json() if code!=204 else None


def inbox(c,who='owner'):
    return call(c,'GET','/notifications',who=who)['items']


def kinds(c,who='owner'):
    return [n['kind'] for n in reversed(inbox(c,who))]


def settings(c,enabled=True,lead=10):
    return call(c,'PUT','/admin/notification-settings',{'enabled':enabled,'lead_minutes':lead})


def sweep(c):
    return call(c,'POST','/admin/reminders/run',{})['created']


def near(c):
    b=grooming(c,start=datetime.now(timezone.utc)+timedelta(minutes=5));assign(c,b);confirm(c,b);return b


def report(c,start=None,end=None):
    return call(c,'GET',f"/admin/dashboard?from_date={start or business_today()}&to_date={end or business_today()}")


def test_customer_notice_lifecycle_and_atomic_denial(case):
    c=case;b=grooming(c);assert kinds(c)==['BOOKING_SUBMITTED']
    confirm(c,b,expected=409);assert kinds(c)==['BOOKING_SUBMITTED']
    assign(c,b);confirm(c,b)
    call(c,'POST',f"/bookings/{b['id']}/reschedule",{'grooming_start':(c['start']+timedelta(days=1)).isoformat()},who='owner')
    assign(c,b);confirm(c,b)
    call(c,'POST',f"/bookings/{b['id']}/cancel",who='owner')
    assert kinds(c)==['BOOKING_SUBMITTED','BOOKING_CONFIRMED','BOOKING_RESCHEDULED','BOOKING_RECONFIRMED','BOOKING_CANCELLED']
    for n in inbox(c):
        assert n['booking_id']==b['id'] and n['created_at'] and n['read_at'] is None
        assert set(n)=={'id','kind','message','booking_id','booking_type','created_at','read_at','schedule_reference','lead_minutes','title','pet_name','service_name','schedule','can_view_booking','cta_label'}
    with SessionLocal() as db:
        for n in db.scalars(select(Notification).where(Notification.recipient_role==Role.CUSTOMER)):
            event=db.get(BookingEvent,n.source_event_id)
            assert event.booking_id==n.booking_id and n.created_at>=event.created_at


@pytest.mark.parametrize('changed',[False,True])
def test_rejection_notice_maps_true_cycle(case,changed):
    c=case;b=boarding(c)
    if changed:
        call(c,'POST',f"/bookings/{b['id']}/reschedule",{'boarding_start':(c['day']+timedelta(days=1)).isoformat(),'boarding_end':(c['day']+timedelta(days=3)).isoformat()},who='owner')
    call(c,'POST',f"/admin/bookings/{b['id']}/status",{'status':'REJECTED'})
    assert kinds(c)[-1]==('RESCHEDULE_REJECTED' if changed else 'BOOKING_REJECTED')


def test_notifications_do_not_invent_care_or_completion_events(stay):
    c=stay;before=kinds(c);through(c)
    assert kinds(c)==before==['BOOKING_SUBMITTED','BOOKING_CONFIRMED']


def test_staff_assignment_reassignment_scoping_and_privacy(case):
    c=case;b=grooming(c);c['staff']=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    c['second']=bearer(login(c['client'],c['seed']['staff2'].email,'DemoPass!123'))
    assign(c,b);assert kinds(c,'staff')==['STAFF_ASSIGNED'] and kinds(c,'second')==[]
    assign(c,b);assert kinds(c,'staff')==['STAFF_ASSIGNED'] # repeated unchanged assignment has no extra notice
    assign(c,b,staff=c['seed']['staff2'].id)
    assert kinds(c,'staff')==['STAFF_ASSIGNED','STAFF_REASSIGNED'] and kinds(c,'second')==['STAFF_REASSIGNED']
    assert c['client'].get(f"/grooming/bookings/{b['id']}",headers=c['staff']).status_code==404
    data=str(inbox(c,'staff'))
    assert 'Customer One' not in data and 'customer.one@' not in data
    assert all(not n['can_view_booking'] for n in inbox(c,'staff')) # saved event pet context is retained
    assert kinds(c)==['BOOKING_SUBMITTED']


def test_boarding_staff_change_notifies_affected_staff(case):
    c=case;b=boarding(c);start=datetime.combine(c['day'],datetime.min.time(),timezone.utc)
    c['staff']=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    assign(c,b)
    assign(c,b,staff=c['seed']['staff2'].id)
    assert kinds(c,'staff')==['STAFF_ASSIGNED','STAFF_REASSIGNED']


def test_inbox_cross_customer_staff_admin_and_anonymous_denials(case):
    c=case;grooming(c);n=inbox(c)[0]
    register_customer(c['client'],'other.inbox@petops.example','Unrelated')
    c['other']=bearer(login(c['client'],'other.inbox@petops.example','CustomerPass!123'))
    c['staff']=bearer(login(c['client'],c['seed']['staff2'].email,'DemoPass!123'))
    for who in ('other','staff'):
        assert inbox(c,who)==[]
        call(c,'GET','/notifications/'+n['id'],who=who,code=404)
        call(c,'POST','/notifications/'+n['id']+'/read',{},who=who,code=404)
    for path in ('/notifications','/notifications/'+n['id']):call(c,'GET',path,code=403)
    call(c,'POST','/notifications/'+n['id']+'/read',{},code=403)
    c['client'].cookies.clear()
    for path in ('/notifications','/notifications/'+n['id']):assert c['client'].get(path).status_code==401
    assert c['client'].post('/notifications/'+n['id']+'/read',json={}).status_code==401


def test_mark_read_idempotent_and_no_spoofed_values(case):
    c=case;grooming(c);n=inbox(c)[0];path='/notifications/'+n['id']+'/read'
    call(c,'POST',path,{'read_at':'2030-01-01T00:00:00Z'},who='owner',code=422)
    saved=call(c,'POST',path,{},who='owner');assert saved['read_at']>=saved['created_at']
    assert call(c,'POST',path,{},who='owner')==saved
    assert call(c,'GET','/notifications',who='owner')['unread_count']==0


@pytest.mark.parametrize('query',['limit=0','limit=201','offset=-1','limit=wrong'])
def test_inbox_pagination_validation(case,query):
    call(case,'GET','/notifications?'+query,who='owner',code=422)


def test_inbox_pagination_does_not_repeat(case):
    c=case;grooming(c);boarding(c)
    a=call(c,'GET','/notifications?limit=1&offset=0',who='owner')
    b=call(c,'GET','/notifications?limit=1&offset=1',who='owner')
    assert a['items'][0]['id']!=b['items'][0]['id'] and a['unread_count']==b['unread_count']==2


def test_reminder_explicit_configuration_due_and_idempotency(case):
    c=case;near(c)
    initial=call(c,'GET','/admin/notification-settings');assert initial['enabled'] is False and initial['lead_minutes'] is None
    assert sweep(c)==0
    settings(c,False,10);assert sweep(c)==0
    settings(c,True,1);assert sweep(c)==0
    settings(c,True,10);assert sweep(c)==1 and sweep(c)==0
    reminder=next(n for n in inbox(c) if n['kind']=='BOOKING_REMINDER')
    assert reminder['lead_minutes']==10 and reminder['schedule_reference']
    assert kinds(c).count('BOOKING_REMINDER')==1


@pytest.mark.parametrize('state',['SUBMITTED','CANCELLED','REJECTED','COMPLETED'])
def test_ineligible_bookings_do_not_remind(case,state):
    c=case;b=grooming(c,start=datetime.now(timezone.utc)+timedelta(minutes=5));settings(c)
    if state=='CANCELLED':call(c,'POST',f"/bookings/{b['id']}/cancel",who='owner')
    if state=='REJECTED':call(c,'POST',f"/admin/bookings/{b['id']}/status",{'status':'REJECTED'})
    if state=='COMPLETED':
        assign(c,b);confirm(c,b);call(c,'POST',f"/grooming/bookings/{b['id']}/start",{})
        call(c,'POST',f"/grooming/bookings/{b['id']}/complete",{})
    assert sweep(c)==0


def test_boarding_midnight_reference_and_past_start_exclusion(case):
    c=case;future=boarding(c,start=business_today()+timedelta(days=1));allocate(c,future);confirm(c,future)
    today=boarding(c,start=business_today());allocate(c,today);confirm(c,today)
    settings(c,True,1440);assert sweep(c)==1
    r=next(n for n in inbox(c) if n['kind']=='BOOKING_REMINDER')
    expected=datetime.combine(business_today()+timedelta(days=1),datetime.min.time(),timezone(timedelta(hours=8))).astimezone(timezone.utc)
    assert r['booking_id']==future['id'] and datetime.fromisoformat(r['schedule_reference'])==expected


def test_reschedule_requires_reconfirmation_and_new_reminder_cycle(case):
    c=case;b=near(c);settings(c);assert sweep(c)==1
    call(c,'POST',f"/bookings/{b['id']}/reschedule",{'grooming_start':(datetime.now(timezone.utc)+timedelta(minutes=7)).isoformat()},who='owner')
    assert sweep(c)==0
    assign(c,b);confirm(c,b);assert sweep(c)==1 and sweep(c)==0
    assert kinds(c).count('BOOKING_REMINDER')==2


def test_simultaneous_reminder_jobs_create_exactly_one(case):
    c=case;near(c);settings(c);barrier=Barrier(2)
    def worker():
        with Session(get_engine()) as db:
            barrier.wait();count=generate_due_reminders(db);db.commit();return count
    with ThreadPoolExecutor(2) as pool:counts=list(pool.map(lambda _:worker(),range(2)))
    assert sum(counts)==1 and kinds(c).count('BOOKING_REMINDER')==1


def test_locked_cancelled_booking_not_reminded(case):
    c=case;b=near(c);settings(c)
    # First real connection owns the booking row until cancellation commits.
    with Session(get_engine()) as db:
        db.execute(select(Booking).where(Booking.id==uuid.UUID(b['id'])).with_for_update())
        with Session(get_engine()) as second:assert generate_due_reminders(second)==0;second.commit()
    call(c,'POST',f"/bookings/{b['id']}/cancel",who='owner');assert sweep(c)==0


@pytest.mark.parametrize('body',[{'enabled':True},{'enabled':True,'lead_minutes':0},{'enabled':True,'lead_minutes':-1},
    {'enabled':True,'lead_minutes':525601},{'enabled':True,'lead_minutes':True},{'enabled':True,'lead_minutes':1.5},
    {'enabled':False,'lead_minutes':10,'updated_by_user_id':str(uuid.uuid4())}])
def test_reminder_config_invalid_boundaries_and_spoof(case,body):
    call(case,'PUT','/admin/notification-settings',body,code=422)
    assert call(case,'GET','/admin/notification-settings')['lead_minutes'] is None


@pytest.mark.parametrize('lead',[1,525600])
def test_reminder_config_valid_bounds_attributed(case,lead):
    c=case;r=settings(c,True,lead)
    assert r['lead_minutes']==lead and r['updated_by_user_id']==str(c['seed']['admin'].id) and r['updated_at']
    e=call(c,'GET','/admin/management-history')[0]
    assert e['action']=='REMINDER_SETTINGS_UPDATED' and e['details']['old']['lead_minutes'] is None


@pytest.mark.parametrize('mutation',["UPDATE notifications SET kind='BOOKING_CANCELLED'",'DELETE FROM notifications',
    "UPDATE notifications SET read_at=created_at-interval '1 second'",'UPDATE notifications SET recipient_user_id=:staff',
    "UPDATE notifications SET read_at=clock_timestamp()+interval '1 day'"])
def test_raw_delivered_notice_immutable(case,mutation):
    c=case;grooming(c)
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):db.execute(text(mutation),{'staff':c['seed']['staff1'].id});db.commit()
        db.rollback()
    assert kinds(c)==['BOOKING_SUBMITTED']


@pytest.mark.parametrize('spoof',['recipient','source','kind','reminder_nulls'])
def test_raw_notification_forgery_denied(case,spoof):
    c=case;b=near(c)
    with SessionLocal() as db:
        old=db.scalar(select(Notification).where(Notification.kind=='BOOKING_CONFIRMED'))
        kwargs={col:getattr(old,col) for col in ('recipient_user_id','recipient_role','booking_id','source_event_id','kind')}
        if spoof=='recipient':kwargs.update(recipient_user_id=c['seed']['staff2'].id,recipient_role=Role.STAFF)
        if spoof=='source':kwargs['source_event_id']=uuid.uuid4()
        if spoof=='kind':kwargs['kind']='EMAIL_SENT'
        if spoof=='reminder_nulls':kwargs['kind']='BOOKING_REMINDER'
        db.add(Notification(**kwargs))
        with pytest.raises(IntegrityError):db.commit()
        db.rollback()


def test_management_staff_create_update_revoke_and_safe_audit(case):
    c=case;new=call(c,'POST','/admin/staff',{'email':'NEW.STAFF@petops.example','password':'FictionalSecret!123'},code=201)
    assert new['email']=='new.staff@petops.example' and 'password' not in str(new)
    token=login(c['client'],new['email'],'FictionalSecret!123')
    call(c,'PUT','/admin/staff/'+new['id'],{'email':'edited.staff@petops.example','is_active':True,'password':'ChangedSecret!123'})
    assert c['client'].get('/me',headers=bearer(token)).status_code==401
    token=login(c['client'],'edited.staff@petops.example','ChangedSecret!123')
    call(c,'PUT','/admin/staff/'+new['id'],{'email':'edited.staff@petops.example','is_active':False})
    assert c['client'].get('/me',headers=bearer(token)).status_code==401
    audit=call(c,'GET','/admin/management-history');assert len(audit)==3
    assert all(e['actor_user_id']==str(c['seed']['admin'].id) for e in audit)
    assert not any(x in str(audit) for x in ('FictionalSecret','ChangedSecret','password_hash'))


def test_staff_account_maintenance_rejects_wrong_role_duplicate_and_active_work(case):
    c=case;sid=str(c['seed']['staff1'].id);b=grooming(c);assign(c,b);confirm(c,b)
    body={'email':c['seed']['staff1'].email,'is_active':False}
    call(c,'PUT','/admin/staff/'+sid,body,code=409)
    assert next(s for s in call(c,'GET','/admin/staff') if s['id']==sid)['is_active']
    assert call(c,'GET','/admin/management-history')==[]
    call(c,'PUT','/admin/staff/'+str(c['seed']['admin'].id),body,code=404)
    call(c,'POST','/admin/staff',{'email':c['seed']['admin'].email,'password':'FictionalPass!123'},code=409)
    call(c,'POST','/admin/staff',{'email':'role.spoof@petops.example','password':'FictionalPass!123','role':'ADMIN'},code=422)


@pytest.mark.parametrize('body',[{'email':'bad','password':'FictionalPass!123'},
    {'email':'x@petops.example','password':'p9!' }, {'email':'x@petops.example','password':'x'*129}])
def test_staff_validation_sanitizes_password(case,body):
    r=call(case,'POST','/admin/staff',body,code=422)
    assert all(set(e)=={'loc','msg','type'} for e in r['detail'])
    assert body['password'] not in str(r)


def test_service_management_bookability_type_and_booking_snapshot(case):
    c=case;s=call(c,'POST','/admin/services',{'name':' New Grooming ','service_type':'GROOMING','duration_minutes':45},code=201)
    assert s['name']=='New Grooming' and s['updated_by_user_id']==str(c['seed']['admin'].id)
    body={'pet_id':c['pet'],'service_id':s['id'],'grooming_start':c['start'].isoformat()}
    b=call(c,'POST','/bookings',body,who='owner',code=201);assert b['grooming_duration_minutes']==45
    call(c,'PUT','/admin/services/'+s['id'],{'name':'Updated Grooming','is_active':True,'duration_minutes':30})
    assert call(c,'GET',f"/grooming/bookings/{b['id']}",who='owner')['booking']['grooming_duration_minutes']==45
    call(c,'PUT','/admin/services/'+s['id'],{'name':'Updated Grooming','is_active':False})
    assert not any(x['id']==s['id'] for x in call(c,'GET','/services',who='owner'))
    call(c,'POST','/bookings',{**body,'grooming_start':(c['start']+timedelta(days=1)).isoformat()},who='owner',code=422)
    call(c,'PUT','/admin/services/'+s['id'],{'name':'Updated Grooming','is_active':True,'service_type':'BOARDING'},code=422)
    assert len(call(c,'GET','/admin/management-history'))==3


@pytest.mark.parametrize('body',[{'name':' ','service_type':'GROOMING','duration_minutes':30},
    {'name':'x','service_type':'GROOMING'},{'name':'x','service_type':'BOARDING','duration_minutes':30},
    {'name':'x','service_type':'GROOMING','duration_minutes':0}, {'name':'x','service_type':'GROOMING','duration_minutes':True},
    {'name':'x','service_type':'GROOMING','duration_minutes':2147483648}])
def test_service_validation(case,body):call(case,'POST','/admin/services',body,code=422)


def test_service_boarding_creation_and_duration_restriction(case):
    c=case;s=call(c,'POST','/admin/services',{'name':'Fictional new Boarding','service_type':'BOARDING'},code=201)
    assert s['duration_minutes'] is None
    call(c,'PUT','/admin/services/'+s['id'],{'name':s['name'],'is_active':True,'duration_minutes':30},code=422)


def test_admin_history_customer_pet_filters_and_prework_changes(case):
    c=case;g=grooming(c);b=boarding(c)
    register_customer(c['client'],'history.other@petops.example','Unrelated history')
    other=bearer(login(c['client'],'history.other@petops.example','CustomerPass!123'))
    op=c['client'].post('/pets',headers=other,json={'name':'Unrelated pet'}).json()
    customers=call(c,'GET','/admin/customers');cid=next(x['id'] for x in customers if x['display_name']=='Customer One')
    assert call(c,'GET',f'/admin/customers/{cid}/pets')==[{'id':c['pet'],'name':'Milo'}]
    rows=call(c,'GET',f"/admin/history?customer_id={cid}&pet_id={c['pet']}&service_type=GROOMING&status=SUBMITTED")
    assert [x['id'] for x in rows['items']]==[g['id']]
    call(c,'GET',f"/admin/history?customer_id={cid}&pet_id={op['id']}",code=404)
    call(c,'GET','/admin/history?from_date='+business_today().isoformat(),code=422)
    call(c,'POST',f"/admin/bookings/{g['id']}/reschedule",{'grooming_start':(c['start']+timedelta(days=1)).isoformat()})
    changed=call(c,'GET',f"/admin/bookings/{g['id']}/history")
    assert changed['history'][-1]['actor_user_id']==str(c['seed']['admin'].id)
    assert kinds(c)[-1]=='BOOKING_RESCHEDULED'
    call(c,'POST',f"/admin/bookings/{b['id']}/cancel",{})
    assert kinds(c)[-1]=='BOOKING_CANCELLED'
    call(c,'GET','/admin/history?limit=0',code=422)
    call(c,'GET','/admin/history?status=MADE_UP',code=422)


def test_admin_does_not_override_active_or_finished_work(stay):
    c=stay;act(c,'check-in')
    for action,body in [('cancel',{}),('reschedule',{'boarding_start':c['day'].isoformat(),'boarding_end':(c['day']+timedelta(days=2)).isoformat()})]:
        call(c,'POST',f"/admin/bookings/{c['b']['id']}/{action}",body,code=409)


def test_all_new_admin_surfaces_reject_customer_staff_and_anonymous(case):
    c=case;sid=str(c['seed']['staff1'].id);svc=str(c['seed']['grooming'].id);bid=grooming(c)['id']
    c['staff']=bearer(login(c['client'],c['seed']['staff1'].email,'DemoPass!123'))
    cid=call(c,'GET','/admin/customers')[0]['id']
    paths=[('GET',p,None) for p in ['/admin/staff','/admin/services','/admin/notification-settings','/admin/customers',f'/admin/customers/{cid}/pets','/admin/history',f'/admin/bookings/{bid}/history','/admin/management-history',f'/admin/dashboard?from_date={business_today()}&to_date={business_today()}']]
    paths += [('POST','/admin/staff',{'email':'deny@petops.example','password':'FictionalPass!123'}),
        ('PUT','/admin/staff/'+sid,{'email':'deny@petops.example','is_active':True}),
        ('POST','/admin/services',{'name':'deny','service_type':'BOARDING'}),
        ('PUT','/admin/services/'+svc,{'name':'deny','is_active':True,'duration_minutes':60}),
        ('PUT','/admin/notification-settings',{'enabled':True,'lead_minutes':10}),
        ('POST','/admin/reminders/run',{}),('POST',f'/admin/bookings/{bid}/cancel',{}),
        ('POST',f'/admin/bookings/{bid}/reschedule',{'grooming_start':c['start'].isoformat()})]
    for method,path,body in paths:
        for who in ('owner','staff'):call(c,method,path,body,who=who,code=403)
        c['client'].cookies.clear();r=c['client'].request(method,path,**({'json':body} if body is not None else {}));assert r.status_code==401
    assert kinds(c)==['BOOKING_SUBMITTED']


@pytest.mark.parametrize('mutation',["UPDATE management_events SET action='STAFF_UPDATED'",'DELETE FROM management_events'])
def test_management_audit_append_only(case,mutation):
    c=case;settings(c)
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):db.execute(text(mutation));db.commit()
        db.rollback()


def test_management_audit_actor_and_typed_target_integrity(case):
    c=case
    with SessionLocal() as db:
        db.add(ManagementEvent(actor_user_id=c['seed']['staff1'].id,action='STAFF_CREATED',staff_user_id=c['seed']['staff2'].id,details={}))
        with pytest.raises(IntegrityError):db.commit()
        db.rollback()
        db.add(ManagementEvent(actor_user_id=c['seed']['admin'].id,action='STAFF_CREATED',staff_user_id=c['seed']['admin'].id,details={}))
        with pytest.raises(IntegrityError):db.commit()
        db.rollback()


def test_dashboard_controlled_counts_completions_changes_and_period(case):
    c=case;g=grooming(c);assign(c,g);confirm(c,g)
    call(c,'POST',f"/grooming/bookings/{g['id']}/start",{});call(c,'POST',f"/grooming/bookings/{g['id']}/complete",{'service_notes':'Fictional report fixture'})
    b=boarding(c);allocate(c,b);confirm(c,b)
    cancelled=grooming(c,start=c['start']+timedelta(days=1));call(c,'POST',f"/bookings/{cancelled['id']}/reschedule",{'grooming_start':(c['start']+timedelta(days=2)).isoformat()},who='owner')
    call(c,'POST',f"/bookings/{cancelled['id']}/cancel",who='owner')
    d=report(c);assert d['total_bookings']==3 and sum(d['bookings_by_status'].values())==3
    assert d['bookings_by_status']['COMPLETED']==1 and d['bookings_by_status']['CONFIRMED']==1 and d['bookings_by_status']['CANCELLED']==1
    assert d['bookings_by_type']=={'GROOMING':2,'BOARDING':1}
    assert d['completed_services_by_type']=={'GROOMING':1,'BOARDING':0}
    assert d['booking_change_events']=={'BOOKING_CANCELLED':1,'BOOKING_RESCHEDULED':1}
    assert d['boarding_current']['configured_active_capacity']==10 and d['boarding_current']['physically_occupied']==0
    past=report(c,business_today()-timedelta(days=2),business_today()-timedelta(days=1))
    assert past['total_bookings']==0 and past['completed_services_by_type']=={'GROOMING':0,'BOARDING':0}
    assert past['booking_change_events']=={'BOOKING_CANCELLED':0,'BOOKING_RESCHEDULED':0}
    assert 'revenue' not in {k.lower() for k in d} and 'cancellation_reasons' not in d


def test_dashboard_occupancy_capacity_and_upcoming_stay(stay):
    c=stay;d=report(c,end=business_today()+timedelta(days=3))
    assert d['upcoming_arrivals']['total']==d['upcoming_departures']['total']==1
    act(c,'check-in');d=report(c)
    assert d['boarding_current']['physically_occupied']==1 and d['boarding_current']['available_places']==9 and d['boarding_current']['utilisation_percent']==10
    assert d['upcoming_arrivals']['total']==0
    act(c,'check-out');d=report(c)
    assert d['boarding_current']['physically_occupied']==0 and d['upcoming_departures']['total']==0
    assert report(c)['completed_services_by_type']['BOARDING']==1


def test_dashboard_workload_overlapping_period_and_cancel_release(case):
    c=case;b=grooming(c);assign(c,b);confirm(c,b)
    d=report(c,c['start'].date(),c['start'].date())
    row=next(s for s in d['staff_workload'] if s['staff_user_id']==str(c['seed']['staff1'].id))
    assert row['active_assigned_bookings_in_period']==1 and row['active_assignments_without_recorded_period']==0
    call(c,'POST',f"/bookings/{b['id']}/cancel",who='owner')
    assert all(s['active_assigned_bookings_in_period']==0 for s in report(c,c['start'].date(),c['start'].date())['staff_workload'])


@pytest.mark.parametrize('query',['from_date=2026-11-10&to_date=2026-11-01','from_date=bad&to_date=2026-11-01',
    'from_date=0001-01-01&to_date=0001-01-01','from_date=9999-12-31&to_date=9999-12-31','from_date=2026-11-01'])
def test_dashboard_date_boundary_validation(case,query):call(case,'GET','/admin/dashboard?'+query,code=422)


def test_dashboard_zero_capacity_and_explicit_local_period(client,seed_base):
    c={'client':client,'admin':bearer(login(client,seed_base['admin'].email,'DemoPass!123'))}
    call(c,'PUT','/admin/accommodations/'+str(seed_base['unit'].id),{'name':'Fictional Test Unit','category':'Fictional','capacity':10,'is_active':False})
    d=report(c);assert d['total_bookings']==0 and d['boarding_current']['utilisation_percent'] is None
    assert d['boarding_current']['available_places']==d['boarding_current']['configured_active_capacity']==0
    lo=datetime.fromisoformat(d['period']['utc_start']);hi=datetime.fromisoformat(d['period']['utc_end_exclusive'])
    assert lo.hour==hi.hour==16 and hi-lo==timedelta(days=1)


def test_dashboard_overdue_open_stay_is_current_occupancy(case):
    from tests.test_slice4 import overdue_fixture
    c=case;c['b']=boarding(c,start=business_today());allocate(c,c['b']);confirm(c,c['b'])
    old=overdue_fixture(c)
    d=report(c);assert d['boarding_current']['physically_occupied']==1
    historical=report(c,business_today()-timedelta(days=10),business_today()-timedelta(days=5))
    assert historical['total_bookings']==0 and historical['boarding_current']['physically_occupied']==1
    assert d['upcoming_arrivals']['total']==1 # overdue stay does not become an upcoming arrival
    act(c,'check-out',headers=c['admin'],bid=old)
    assert report(c)['boarding_current']['physically_occupied']==0


def test_notification_transaction_rolls_back_with_event(case):
    c=case
    with SessionLocal() as db:
        customer=db.scalar(select(Customer))
        b=Booking(customer_id=customer.id,pet_id=uuid.UUID(c['pet']),service_id=c['seed']['grooming'].id,
            booking_type='GROOMING',status='SUBMITTED',grooming_start=c['start'],grooming_duration_minutes=60,created_by_user_id=customer.user_id)
        db.add(b);db.flush()
        db.add(BookingEvent(booking_id=b.id,event_type='BOOKING_SUBMITTED',new_status='SUBMITTED',actor_user_id=customer.user_id))
        db.flush();assert db.scalar(select(func.count()).select_from(Notification))==1
        db.rollback()
    assert inbox(c)==[]
