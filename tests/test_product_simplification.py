"""Controlled D changes: responsibility periods, service order and scoped event feeds."""
from datetime import datetime,timedelta,timezone
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import select,text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from app.database import SessionLocal
from app.main import app
from app.models import Booking,StaffResponsibility,User
from app.services import business_today
from tests.conftest import login,register_customer
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case,grooming,boarding,assign,allocate,confirm

def staff_auth(c,number=1):return bearer(login(c['client'],c['seed'][f'staff{number}'].email,'DemoPass!123'))
def detail(c,b,auth=None):
    r=c['client'].get(f"/{b['booking_type'].lower()}/bookings/{b['id']}",headers=auth or c['admin']);assert r.status_code==200,r.text;return r.json()
def started_stay(c):
    b=boarding(c,start=business_today(),end=business_today()+timedelta(days=3));allocate(c,b);assign(c,b);confirm(c,b)
    r=c['client'].post(f"/boarding/bookings/{b['id']}/check-in",headers=c['admin'],json={});assert r.status_code==200,r.text;return b
def deactivate(c,number=1):
    u=c['seed'][f'staff{number}'];return c['client'].put(f'/admin/staff/{u.id}',headers=c['admin'],json={'email':u.email,'is_active':False})

def test_active_staff_needs_no_generic_window(case):
    c=case
    with SessionLocal() as db:db.execute(text('DELETE FROM staff_availability'));db.commit()
    b=grooming(c);assign(c,b);confirm(c,b)
    d=detail(c,b)['booking'];assert d['staff_start']==d['grooming_start'];assert datetime.fromisoformat(d['staff_end'])-datetime.fromisoformat(d['staff_start'])==timedelta(minutes=60)

def test_inactive_staff_is_not_assignable(case):
    c=case;assert deactivate(c).status_code==200;b=grooming(c);assign(c,b,expected=409)

@pytest.mark.parametrize('kind',['grooming','boarding'])
def test_future_work_blocks_deactivation(case,kind):
    c=case;b=grooming(c) if kind=='grooming' else boarding(c);assign(c,b);assert deactivate(c).status_code==409
    assign(c,b,staff=c['seed']['staff2'].id);assert deactivate(c).status_code==200

@pytest.mark.parametrize('method,path',[('post','/admin/staff/{id}/availability'),('put','/admin/staff/{id}/availability/{id}'),('get','/staff/availability')])
def test_retired_availability_routes_are_explicit(case,method,path):
    c=case;auth=staff_auth(c) if method=='get' else c['admin'];kw={} if method=='get' else {'json':{'starts_at':c['start'].isoformat(),'ends_at':(c['start']+timedelta(hours=1)).isoformat(),'is_active':True}}
    r=getattr(c['client'],method)(path.format(id=c['seed']['staff1'].id),headers=auth,**kw);assert r.status_code==410,r.text

def test_boarding_initial_period_is_stay_not_manual_entry(case):
    c=case;b=boarding(c);assign(c,b);d=detail(c,b);r=d['responsibilities'][0]
    assert datetime.fromisoformat(r['starts_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat()==b['boarding_start']
    assert datetime.fromisoformat(r['ends_at']).astimezone(timezone(timedelta(hours=8))).date().isoformat()==b['boarding_end']
    assert datetime.fromisoformat(r['starts_at']).hour==16
    assign(c,b,expected=422,starts_at=c['start'].isoformat(),ends_at=(c['start']+timedelta(hours=1)).isoformat())

def test_mid_stay_handover_preserves_history_and_access(case):
    c=case;b=started_stay(c);old=detail(c,b)['responsibilities'][0];before=staff_auth(c);after=staff_auth(c,2)
    assign(c,b,staff=c['seed']['staff2'].id);d=detail(c,b);r1,r2=d['responsibilities']
    assert len(d['responsibilities'])==2 and r1['ends_at']==old['ends_at'] and r1['effective_end']==r2['starts_at'] and r1['staff_user_id']!=r2['staff_user_id']
    assert c['client'].get(f"/boarding/bookings/{b['id']}",headers=before).status_code==404
    assert detail(c,b,after)['booking']['current_staff_user_id']==str(c['seed']['staff2'].id)
    assert deactivate(c).status_code==200
    r=c['client'].post(f"/boarding/bookings/{b['id']}/notes",headers=after,json={'note':'Fictional handover update.'});assert r.status_code==201,r.text
    r=c['client'].post(f"/boarding/bookings/{b['id']}/check-out",headers=after,json={});assert r.status_code==200,r.text
    assert r.json()['booking']['status']=='COMPLETED' and len(r.json()['responsibilities'])==2

def test_future_handover_keeps_current_actor_and_scopes_future_staff(case):
    c=case;b=started_stay(c);when=datetime.now(timezone.utc)+timedelta(hours=2);assign(c,b,staff=c['seed']['staff2'].id,effective_at=when.isoformat());old=staff_auth(c);new=staff_auth(c,2)
    assert detail(c,b,old)['booking']['current_staff_user_id']==str(c['seed']['staff1'].id);detail(c,b,new)
    r=c['client'].post(f"/boarding/bookings/{b['id']}/notes",headers=new,json={'note':'Too soon.'});assert r.status_code==403
    r=c['client'].post(f"/boarding/bookings/{b['id']}/notes",headers=old,json={'note':'Current responsibility.'});assert r.status_code==201,r.text

@pytest.mark.parametrize('hours',[-1,100])
def test_invalid_handover_time_rejected_without_mutation(case,hours):
    c=case;b=started_stay(c);before=detail(c,b)['responsibilities'];assign(c,b,staff=c['seed']['staff2'].id,expected=422,effective_at=(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat());assert detail(c,b)['responsibilities']==before

def test_handover_conflict_is_rejected(case):
    c=case;other=boarding(c,start=business_today(),end=business_today()+timedelta(days=3));assign(c,other,staff=c['seed']['staff2'].id);b=started_stay(c);assign(c,b,staff=c['seed']['staff2'].id,expected=409);assert len(detail(c,b)['responsibilities'])==1

def test_grooming_reassignment_stops_at_fulfilment(case):
    c=case;b=grooming(c);assign(c,b);confirm(c,b);assign(c,b,staff=c['seed']['staff2'].id);assert len(detail(c,b)['responsibilities'])==2
    r=c['client'].post(f"/grooming/bookings/{b['id']}/start",headers=c['admin'],json={});assert r.status_code==200,r.text;assign(c,b,expected=409)

def test_responsibility_original_period_and_deletion_guarded(case):
    c=case;b=grooming(c);assign(c,b)
    for sql in ["UPDATE staff_responsibilities SET ends_at=ends_at+interval '1 minute'","DELETE FROM staff_responsibilities"]:
        with SessionLocal() as db:
            with pytest.raises(IntegrityError):db.execute(text(sql));db.commit()
            db.rollback()

def test_service_order_active_selection_and_retained_identity(case):
    c=case;b=grooming(c);s=c['seed']['grooming'];body={'name':s.name,'is_active':True,'duration_minutes':60,'display_order':20}
    r=c['client'].put(f'/admin/services/{s.id}',headers=c['admin'],json=body);assert r.status_code==200
    r=c['client'].post('/admin/services',headers=c['admin'],json={'name':'Z First Grooming','service_type':'GROOMING','duration_minutes':30,'display_order':1});assert r.status_code==201;r1=r.json()
    rows=c['client'].get('/services',headers=c['owner']).json();assert [x['name'] for x in rows if x['service_type']=='GROOMING']==['Z First Grooming','Basic Grooming']
    body['is_active']=False;c['client'].put(f'/admin/services/{s.id}',headers=c['admin'],json=body)
    assert str(s.id) not in [x['id'] for x in c['client'].get('/services',headers=c['owner']).json()]
    assert detail(c,b,c['owner'])['service_name']=='Basic Grooming'
    assert c['client'].delete(f'/admin/services/{s.id}',headers=c['admin']).status_code==405

def test_pet_archive_keeps_history_and_ownership(case):
    c=case;b=grooming(c);register_customer(c['client'],'other.product@petops.example');auth=bearer(login(c['client'],'other.product@petops.example','CustomerPass!123'))
    assert c['client'].post(f"/pets/{c['pet']}/archive",headers=auth,json={}).status_code==404
    r=c['client'].post(f"/pets/{c['pet']}/archive",headers=c['owner'],json={});assert r.status_code==200
    assert detail(c,b,c['owner'])['booking']['pet_id']==c['pet'];grooming(c,start=c['start']+timedelta(days=1),expected=404)
    assert c['client'].delete(f"/pets/{c['pet']}",headers=c['owner']).status_code==409

def test_notification_current_and_removed_access_is_server_determined(case):
    c=case;b=grooming(c);assign(c,b);old=staff_auth(c);new=staff_auth(c,2)
    notice=c['client'].get('/notifications',headers=old).json()['items'][0];assert notice['can_view_booking'] and notice['pet_name'] and notice['schedule']['grooming_start']
    assign(c,b,staff=c['seed']['staff2'].id);items=c['client'].get('/notifications',headers=old).json()['items'];assert all(not n['can_view_booking'] and n['cta_label'] is None for n in items)
    assert 'no longer responsible' in items[0]['message'];assert 'assigned this Grooming' in c['client'].get('/notifications',headers=new).json()['items'][0]['message']
    assert c['client'].get('/notifications/'+items[0]['id'],headers=new).status_code==404
    confirm(c,b);notices=c['client'].get('/notifications',headers=c['owner']).json()['items'];assert notices[0]['message']=='Your Grooming request has been confirmed.'

def test_account_fields_remain_scoped(case):
    c=case;auth=staff_auth(c);r=c['client'].put('/account',headers=auth,json={'display_name':'Aisyah Fictional'});assert r.status_code==200,r.text
    assert c['client'].get('/me',headers=auth).json()['display_name']=='Aisyah Fictional'
    assert c['client'].put('/account',headers=auth,json={'display_name':'Aisyah','role':'ADMIN'}).status_code==422
    assert c['client'].put('/account',headers=c['owner'],json={'display_name':'Other'}).status_code==403
    assert c['client'].put('/customer/profile',headers=c['owner'],json={'display_name':'Fictional Owner','user_id':str(c['seed']['staff1'].id)}).status_code==422

def test_report_search_date_basis_sort_and_metrics(case):
    c=case;b=grooming(c);b2=boarding(c);today=business_today().isoformat();base='/admin/history'
    data=c['client'].get(base,headers=c['admin'],params={'search':'customer one','sort':'oldest','date_basis':'created','from_date':today,'to_date':today}).json();assert data['total']==2 and data['items'][0]['id']==b['id']
    data=c['client'].get(base,headers=c['admin'],params={'date_basis':'service','from_date':b2['boarding_start'],'to_date':b2['boarding_start']}).json();assert [x['id'] for x in data['items']]==[b2['id']]
    assert c['client'].get(base,headers=c['admin'],params={'search':'no such pet'}).json()['total']==0
    assert c['client'].get(base,headers=c['admin']).json()['total']==2
    d=c['client'].get('/admin/dashboard',headers=c['admin'],params={'from_date':today,'to_date':today}).json();assert d['total_bookings']==2 and d['bookings_by_status']['SUBMITTED']==2 and d['boarding_current']['physically_occupied']==0

def test_two_simultaneous_assignments_cannot_claim_same_staff(case):
    c=case;b1=grooming(c);b2=grooming(c);barrier=Barrier(2)
    def attempt(b):
        with TestClient(app) as client:
            barrier.wait(timeout=10);return client.put(f"/admin/bookings/{b['id']}/staff",headers=c['admin'],json={'staff_user_id':str(c['seed']['staff1'].id)}).status_code
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,[b1,b2]))
    assert sorted(results)==[200,409]

def test_grooming_work_does_not_disappear_after_planned_period(case,monkeypatch):
    c=case;b=grooming(c);assign(c,b);confirm(c,b);auth=staff_auth(c)
    import app.responsibilities as responsibilities
    monkeypatch.setattr(responsibilities,'utcnow',lambda:datetime.fromisoformat(b['grooming_start'])+timedelta(hours=2))
    detail(c,b,auth)
    r=c['client'].post(f"/grooming/bookings/{b['id']}/start",headers=auth,json={});assert r.status_code==200,r.text
    detail(c,b,auth)
    r=c['client'].post(f"/grooming/bookings/{b['id']}/complete",headers=auth,json={});assert r.status_code==200,r.text

@pytest.mark.parametrize('mutation',["ended_at=clock_timestamp(),ended_by_user_id=:actor","released_at=clock_timestamp()"])
def test_active_responsibility_cannot_be_shortened_or_withdrawn_without_handover(case,mutation):
    c=case;b=started_stay(c)
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(text('UPDATE staff_responsibilities SET '+mutation+' WHERE booking_id=:bid'),{'bid':UUID(b['id']),'actor':c['seed']['admin'].id});db.commit()
        db.rollback()

def test_pending_handover_can_be_replaced_at_same_instant_with_history(case):
    c=case;b=started_stay(c);when=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat();assign(c,b,staff=c['seed']['staff2'].id,effective_at=when);assign(c,b,effective_at=when)
    rows=detail(c,b)['responsibilities'];assert len(rows)==3 and sum(r['released_at'] is not None for r in rows)==1
    current=[r for r in rows if not r['released_at']];assert current[0]['effective_end']==current[1]['starts_at']

def test_report_rejects_nul_search(case):
    assert case['client'].get('/admin/history',headers=case['admin'],params={'search':'invalid\x00search'}).status_code==422
