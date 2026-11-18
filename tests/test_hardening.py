"""Frozen first-slice security/integrity regressions; no fulfilment features.

CONFIRMED/fulfilment states below are fixture-only data, not claims that the
unimplemented availability/assignment/fulfilment workflows were executed.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.database import SessionLocal, get_engine
from app.main import app
from app.models import Booking, BookingEvent, BookingStatus, Customer, Pet, Role, Service, StaffAvailability, User, UserSession
from app.services import business_today, cancel_booking, reschedule_booking
from tests.conftest import login, register_customer
from tests.test_vertical_slice import bearer, make_customer_with_pet


def future(days=2):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture
def booking_case(client, seed_base):
    token, pet = make_customer_with_pet(client)
    response = client.post('/bookings', headers=bearer(token), json={
        'pet_id': pet, 'service_id': str(seed_base['grooming'].id), 'grooming_start': future()})
    assert response.status_code == 201, response.text
    return token, pet, response.json()


def counts():
    with SessionLocal() as db:
        return tuple(db.scalar(select(func.count()).select_from(model))
                     for model in (User, Customer, Pet, Booking, BookingEvent, UserSession))


def protected_requests(booking_id, pet_id):
    return [
        ('GET', '/me', None), ('GET', '/services', None),
        ('GET', '/customer/profile', None), ('PUT', '/customer/profile', {'display_name': 'Changed'}),
        ('GET', '/pets', None), ('POST', '/pets', {'name': 'Changed'}),
        ('PUT', f'/pets/{pet_id}', {'name': 'Changed'}), ('DELETE', f'/pets/{pet_id}', None),
        ('GET', '/bookings', None), ('POST', '/bookings', {'pet_id': pet_id, 'service_id': str(uuid.uuid4()), 'grooming_start': future()}),
        ('GET', f'/bookings/{booking_id}', None), ('GET', f'/bookings/{booking_id}/history', None),
        ('POST', f'/bookings/{booking_id}/cancel', None),
        ('POST', f'/bookings/{booking_id}/reschedule', {'grooming_start': future(4)}),
        ('GET', f'/staff/bookings/{booking_id}', None), ('GET', f'/admin/bookings/{booking_id}', None),
        ('POST', f'/admin/bookings/{booking_id}/status', {'status': 'REJECTED'}),
    ]


def test_every_protected_endpoint_rejects_anonymous_without_changes(client, booking_case):
    _, pet, b = booking_case
    client.cookies.clear()
    before = counts()
    for method, path, body in protected_requests(b['id'], pet):
        response = client.request(method, path, json=body)
        assert response.status_code == 401, (method, path, response.text)
    assert counts() == before


def test_role_matrix_denials_do_not_mutate(client, seed_base, booking_case):
    customer, pet, b = booking_case
    staff = login(client, seed_base['staff1'].email, 'DemoPass!123')
    admin = login(client, seed_base['admin'].email, 'DemoPass!123')
    before = counts()
    for role, token in [('CUSTOMER', customer), ('STAFF', staff), ('ADMIN', admin)]:
        for method, path, body in protected_requests(b['id'], pet):
            if path in {'/me', '/services'}:
                continue
            expected = 'STAFF' if path.startswith('/staff/') else 'ADMIN' if path.startswith('/admin/') else 'CUSTOMER'
            if role != expected:
                r = client.request(method, path, json=body, headers=bearer(token))
                assert r.status_code == 403, (role, method, path, r.text)
    assert counts() == before
    assert client.get(f"/bookings/{b['id']}", headers=bearer(customer)).json()['status'] == 'SUBMITTED'
    assert client.get('/pets', headers=bearer(customer)).json()[0]['name'] == 'Milo'


def test_all_cross_customer_record_paths_are_isolated(client, booking_case):
    owner, pet, b = booking_case
    register_customer(client, 'customer.two@petops.example', 'Two')
    other = login(client, 'customer.two@petops.example', 'CustomerPass!123')
    before = counts()
    for method, path, body in protected_requests(b['id'], pet):
        if path.startswith(f"/bookings/{b['id']}") or path == f'/pets/{pet}':
            assert client.request(method, path, json=body, headers=bearer(other)).status_code == 404
    assert client.get('/bookings', headers=bearer(other)).json() == []
    assert client.get('/pets', headers=bearer(other)).json() == []
    assert client.put('/customer/profile', headers=bearer(other), json={'display_name': 'Two Updated'}).status_code == 200
    assert client.get('/customer/profile', headers=bearer(owner)).json()['display_name'] == 'Customer One'
    assert counts() == before


@pytest.mark.parametrize('kind', ['forged', 'expired', 'inactive', 'deleted'])
def test_unusable_sessions_fail_closed(client, booking_case, kind):
    token, _, _ = booking_case
    digest = hashlib.sha256(token.encode()).hexdigest()
    with SessionLocal() as db:
        row = db.scalar(select(UserSession).where(UserSession.token_hash == digest))
        assert row.token_hash != token and len(row.token_hash) == 64
        if kind == 'expired':
            row.created_at = datetime.now(timezone.utc) - timedelta(days=2)
            row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        elif kind == 'inactive':
            db.get(User, row.user_id).is_active = False
        elif kind == 'deleted':
            db.delete(row)
        db.commit()
    assert client.get('/me', headers=bearer('forged' if kind == 'forged' else token)).status_code == 401
    if kind == 'inactive':
        assert client.post('/auth/login', json={'email': 'customer.one@petops.example', 'password': 'CustomerPass!123'}).status_code == 401


def test_login_failure_issues_no_session_and_cookie_flags(client, booking_case, monkeypatch):
    before = counts()
    assert client.post('/auth/login', json={'email': 'unknown@petops.example', 'password': 'CustomerPass!123'}).status_code == 401
    assert client.post('/auth/login', json={'email': 'customer.one@petops.example', 'password': 'wrong'}).status_code == 401
    assert counts() == before
    monkeypatch.setenv('PETOPS_ENV', 'production')
    r = client.post('/auth/login', json={'email': 'customer.one@petops.example', 'password': 'CustomerPass!123'})
    cookie = r.headers['set-cookie'].lower()
    assert all(flag in cookie for flag in ('httponly', 'secure', 'samesite=strict'))


@pytest.mark.parametrize('field,value', [('display_name',' '), ('display_name','\t\n'), ('display_name','x'*121), ('password','x'*9), ('password','x'*129), ('email','invalid'), ('role','ADMIN'), ('customer_id',str(uuid.uuid4()))])
def test_registration_invalid_boundaries_and_privilege_injection(client, field, value):
    payload = {'email':'new@petops.example', 'password':'CustomerPass!123', 'display_name':'New'}
    payload[field] = value
    r = client.post('/auth/register', json=payload)
    assert r.status_code == 422
    assert payload['password'] not in r.text
    assert counts()[:2] == (0, 0)


def test_registration_normalization_duplicate_and_password_storage(client):
    r = client.post('/auth/register', json={'email':' New@petops.example ', 'password':'x'*10, 'display_name':'  N  '})
    assert r.status_code == 201 and r.json()['email'] == 'new@petops.example'
    assert client.post('/auth/register', json={'email':'NEW@petops.example', 'password':'x'*10, 'display_name':'Duplicate'}).status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(Customer)).display_name == 'N'
        assert db.scalar(select(User)).password_hash.startswith('scrypt$')
        assert db.scalar(select(User)).password_hash != 'x'*10


def test_duplicate_registration_race_returns_conflict(client):
    def register_once(_):
        with TestClient(app) as c:
            return c.post('/auth/register', json={'email':'race@petops.example','password':'CustomerPass!123','display_name':'Race'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(register_once, range(2))) == [201,409]
    assert counts()[:2] == (1,1)


@pytest.mark.parametrize('value', ['', ' ', '\u2003', 'x'*121])
def test_profile_and_pet_reject_blank_and_long_names(client, booking_case, value):
    token, pet, _ = booking_case
    before = counts()
    for method, path, payload in [('PUT','/customer/profile',{'display_name':value}), ('POST','/pets',{'name':value}), ('PUT',f'/pets/{pet}',{'name':value})]:
        assert client.request(method,path,json=payload,headers=bearer(token)).status_code == 422
    assert counts() == before


def test_valid_profile_pet_boundaries_and_unreferenced_delete(client, booking_case):
    token, _, _ = booking_case
    assert client.put('/customer/profile', headers=bearer(token), json={'display_name':'x'*120}).status_code == 200
    pet = client.post('/pets', headers=bearer(token), json={'name':'  A  '}).json()
    assert pet['name'] == 'A'
    assert client.put(f"/pets/{pet['id']}", headers=bearer(token), json={'name':'x'*120}).status_code == 200
    assert client.delete(f"/pets/{pet['id']}", headers=bearer(token)).status_code == 204


@pytest.mark.parametrize('schedule', [{}, {'grooming_start':'2020-01-01T00:00:00Z'}, {'grooming_start':'2030-01-01T00:00:00'}, {'grooming_start':'bad'}, {'boarding_start':'2030-01-02'}, {'boarding_start':'2030-01-02','boarding_end':'2030-01-02'}, {'boarding_start':'2030-01-02','boarding_end':'2030-01-01'}, {'boarding_start':'2020-01-01','boarding_end':'2020-01-02'}, {'grooming_start':'2030-01-01T00:00:00Z','boarding_start':'2030-01-01','boarding_end':'2030-01-02'}])
def test_invalid_booking_and_reschedule_leave_data_unchanged(client, seed_base, booking_case, schedule):
    token, pet, b = booking_case
    before = counts()
    assert client.post('/bookings', headers=bearer(token), json={'pet_id':pet,'service_id':str(seed_base['grooming'].id),**schedule}).status_code == 422
    assert client.post(f"/bookings/{b['id']}/reschedule", headers=bearer(token), json=schedule).status_code == 422
    assert counts() == before
    assert client.get(f"/bookings/{b['id']}", headers=bearer(token)).json() == b


def test_bad_identifiers_type_mismatch_and_spoofed_fields(client, seed_base, booking_case):
    token, pet, b = booking_case
    base = {'pet_id':pet,'service_id':str(seed_base['grooming'].id),'grooming_start':future()}
    for changes, expected in [({'pet_id':'bad'},422),({'pet_id':str(uuid.uuid4())},404),({'service_id':str(uuid.uuid4())},422),({'customer_id':str(uuid.uuid4())},422),({'status':'CONFIRMED'},422),({'assigned_staff_user_id':str(seed_base['staff1'].id)},422),({'service_id':str(seed_base['boarding'].id)},422)]:
        assert client.post('/bookings',headers=bearer(token),json={**base,**changes}).status_code == expected
    assert client.get('/bookings/not-a-uuid',headers=bearer(token)).status_code == 422


def test_boarding_today_and_reschedule_history_and_timezone(client, seed_base, booking_case):
    token, pet, _ = booking_case
    today = business_today()
    payload = {'pet_id':pet,'service_id':str(seed_base['boarding'].id),'boarding_start':today.isoformat(),'boarding_end':(today+timedelta(days=1)).isoformat()}
    b = client.post('/bookings',headers=bearer(token),json=payload)
    assert b.status_code == 201
    bid = b.json()['id']
    r = client.post(f'/bookings/{bid}/reschedule',headers=bearer(token),json={'boarding_start':(today+timedelta(days=2)).isoformat(),'boarding_end':(today+timedelta(days=3)).isoformat()})
    assert r.status_code == 200 and r.json()['status'] == 'SUBMITTED'
    history = client.get(f'/bookings/{bid}/history',headers=bearer(token)).json()
    assert history[-1]['old_schedule']['boarding_start'] == today.isoformat()
    assert history[-1]['new_schedule']['boarding_start'] == (today+timedelta(days=2)).isoformat()
    # Offset represents an instant; store/return UTC rather than relabelling it.
    offset = (datetime.now(timezone(timedelta(hours=8)))+timedelta(days=4)).isoformat()
    r = client.post('/bookings',headers=bearer(token),json={'pet_id':pet,'service_id':str(seed_base['grooming'].id),'grooming_start':offset})
    assert r.status_code == 201
    assert datetime.fromisoformat(r.json()['grooming_start']).replace(tzinfo=timezone.utc) == datetime.fromisoformat(offset).astimezone(timezone.utc)


def test_inactive_service_cannot_be_rescheduled_but_can_be_cancelled(client, seed_base, booking_case):
    token, _, b = booking_case
    with SessionLocal() as db:
        db.get(Service, seed_base['grooming'].id).is_active = False
        db.commit()
    before = counts()
    assert client.post(f"/bookings/{b['id']}/reschedule",headers=bearer(token),json={'grooming_start':future(5)}).status_code == 422
    assert counts() == before
    assert client.post(f"/bookings/{b['id']}/cancel",headers=bearer(token)).status_code == 200


@pytest.mark.parametrize('kind,status', [('GROOMING',s) for s in ('IN_PROGRESS','COMPLETED','REJECTED','CANCELLED')] + [('BOARDING',s) for s in ('STAYING','COMPLETED','REJECTED','CANCELLED')])
def test_all_prohibited_customer_change_states(client, seed_base, booking_case, kind, status):
    token, pet, b = booking_case
    if kind == 'BOARDING':
        today = business_today()
        b = client.post('/bookings',headers=bearer(token),json={'pet_id':pet,'service_id':str(seed_base['boarding'].id),'boarding_start':today.isoformat(),'boarding_end':(today+timedelta(days=2)).isoformat()}).json()
    if kind == 'GROOMING' and status in {'IN_PROGRESS', 'COMPLETED'}:
        # Slice 3 now requires real attributed operational records/events.
        admin = bearer(login(client, seed_base['admin'].email, 'DemoPass!123'))
        assert client.put(f"/admin/bookings/{b['id']}/staff", headers=admin, json={'staff_user_id': str(seed_base['staff1'].id)}).status_code == 200
        assert client.post(f"/admin/bookings/{b['id']}/status", headers=admin, json={'status': 'CONFIRMED'}).status_code == 200
        assert client.post(f"/grooming/bookings/{b['id']}/start", headers=admin, json={}).status_code == 200
        if status == 'COMPLETED':
            assert client.post(f"/grooming/bookings/{b['id']}/complete", headers=admin, json={}).status_code == 200
    elif kind == 'BOARDING' and status in {'CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED'}:
        # Slice 4 now uses actual attributed Boarding operations and releases.
        admin = bearer(login(client, seed_base['admin'].email, 'DemoPass!123'))
        assert client.put(f"/admin/bookings/{b['id']}/accommodation", headers=admin, json={'accommodation_id': str(seed_base['unit'].id)}).status_code == 200
        assert client.post(f"/admin/bookings/{b['id']}/status", headers=admin, json={'status':'CONFIRMED'}).status_code == 200
        for action, target in [('check-in','STAYING'),('check-out','COMPLETED')]:
            response=client.post(f"/boarding/bookings/{b['id']}/{action}",headers=admin,json={})
            assert response.status_code == 200, response.text
            if target == status: break
    else:
        with SessionLocal() as db:
            db.get(Booking,uuid.UUID(b['id'])).status = BookingStatus(status)
            db.commit()
    before = counts()
    assert client.post(f"/bookings/{b['id']}/cancel",headers=bearer(token)).status_code == 409
    assert client.post(f"/bookings/{b['id']}/reschedule",headers=bearer(token),json={'grooming_start':future(6)}).status_code == 409
    assert counts() == before
    assert client.get(f"/bookings/{b['id']}",headers=bearer(token)).json()['status'] == status


def test_confirmation_is_blocked_and_rejection_audited(client, seed_base, booking_case):
    token, _, b = booking_case
    admin = login(client,seed_base['admin'].email,'DemoPass!123')
    before = counts()
    r = client.post(f"/admin/bookings/{b['id']}/status",headers=bearer(admin),json={'status':'CONFIRMED'})
    assert r.status_code == 409 and 'BR-002' in r.text
    assert counts() == before
    assert client.post(f"/admin/bookings/{b['id']}/status",headers=bearer(admin),json={'status':'REJECTED'}).status_code == 200
    # Actor attribution is audited in the Admin history (2026-11-18 D4); the owner sees the outcome without actor ids.
    h = client.get(f"/admin/bookings/{b['id']}/history",headers=bearer(admin)).json()['history']
    assert h[-1]['actor_user_id'] == str(seed_base['admin'].id)
    assert (h[-1]['old_status'],h[-1]['new_status']) == ('SUBMITTED','REJECTED')
    assert datetime.fromisoformat(h[-1]['created_at'])
    mine = client.get(f"/bookings/{b['id']}/history",headers=bearer(token)).json()[-1]
    assert (mine['old_status'],mine['new_status']) == ('SUBMITTED','REJECTED') and 'actor_user_id' not in mine


def test_reschedule_revokes_assignment_and_preserves_previous_staff(client, seed_base, booking_case):
    token, _, b = booking_case
    admin = login(client,seed_base['admin'].email,'DemoPass!123')
    assert client.put(f"/admin/bookings/{b['id']}/staff",headers=bearer(admin),json={'staff_user_id':str(seed_base['staff1'].id)}).status_code == 200
    assert client.post(f"/admin/bookings/{b['id']}/status",headers=bearer(admin),json={'status':'CONFIRMED'}).status_code == 200
    staff = login(client,seed_base['staff1'].email,'DemoPass!123')
    assert client.get(f"/staff/bookings/{b['id']}",headers=bearer(staff)).status_code == 200
    r = client.post(f"/bookings/{b['id']}/reschedule",headers=bearer(token),json={'grooming_start':future(5)})
    assert r.status_code == 200 and 'assigned_staff_user_id' not in r.json()  # Customer view is minimised (D4)
    assert client.get(f"/admin/bookings/{b['id']}",headers=bearer(admin)).json()['assigned_staff_user_id'] is None
    assert client.get(f"/staff/bookings/{b['id']}",headers=bearer(staff)).status_code == 404
    h = client.get(f"/admin/bookings/{b['id']}/history",headers=bearer(admin)).json()['history'][-1]
    assert h['old_assigned_staff_user_id'] == str(seed_base['staff1'].id)
    assert h['new_assigned_staff_user_id'] is None
    assert h['old_status'] == 'CONFIRMED' and h['new_status'] == 'SUBMITTED'


def test_stale_booking_change_rolls_back_history(client, booking_case):
    _, _, b = booking_case
    with SessionLocal() as first, SessionLocal() as second:
        a = first.get(Booking,uuid.UUID(b['id']))
        stale = second.get(Booking,a.id)
        actor1 = first.get(User,a.created_by_user_id)
        actor2 = second.get(User,stale.created_by_user_id)
        cancel_booking(first,a,actor1)
        with pytest.raises(StaleDataError):
            reschedule_booking(second,stale,actor2,grooming_start=datetime.now(timezone.utc)+timedelta(days=6))
        second.rollback()
    with SessionLocal() as db:
        row = db.get(Booking,uuid.UUID(b['id']))
        assert row.status == BookingStatus.CANCELLED
        assert [e.event_type for e in db.scalars(select(BookingEvent).where(BookingEvent.booking_id==row.id).order_by(BookingEvent.created_at))] == ['BOOKING_SUBMITTED','BOOKING_CANCELLED']


@pytest.mark.parametrize('defect', ['service_type','staff_role','creator','schedule','status_type','version','orphan_service','orphan_pet','null_customer'])
def test_database_rejects_invalid_booking_mutations(client, seed_base, booking_case, defect):
    _, _, b = booking_case
    with SessionLocal() as db:
        row = db.get(Booking,uuid.UUID(b['id']))
        if defect == 'service_type': row.service_id = seed_base['boarding'].id
        elif defect == 'staff_role': row.assigned_staff_user_id = seed_base['admin'].id
        elif defect == 'creator': row.created_by_user_id = seed_base['admin'].id
        elif defect == 'schedule': row.boarding_start = business_today()
        elif defect == 'status_type': row.status = BookingStatus.CHECKED_IN
        elif defect == 'version':
            with pytest.raises(IntegrityError): db.execute(update(Booking).where(Booking.id==row.id).values(version=0))
            db.rollback()
            return
        elif defect == 'orphan_service': row.service_id = uuid.uuid4()
        elif defect == 'orphan_pet': row.pet_id = uuid.uuid4()
        elif defect == 'null_customer': row.customer_id = None
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


@pytest.mark.parametrize('defect', ['customer_role','blank_pet','blank_customer','blank_service','email_case','customer_role_change','staff_role_change'])
def test_database_rejects_invalid_account_and_name_links(client, seed_base, booking_case, defect):
    _, pet, b = booking_case
    if defect == 'staff_role_change':
        # PS-02/0008: valid assignment includes responsibility and attributed history.
        admin = bearer(login(client, seed_base['admin'].email, 'DemoPass!123'))
        response = client.put(f"/admin/bookings/{b['id']}/staff", headers=admin,
                              json={'staff_user_id': str(seed_base['staff1'].id)})
        assert response.status_code == 200, response.text
    with SessionLocal() as db:
        row = db.get(Booking,uuid.UUID(b['id']))
        customer = db.get(Customer,row.customer_id)
        if defect == 'customer_role': db.add(Customer(user_id=seed_base['admin'].id,display_name='Invalid'))
        elif defect == 'blank_pet': db.get(Pet,uuid.UUID(pet)).name = ' '
        elif defect == 'blank_customer': customer.display_name = ' '
        elif defect == 'blank_service': db.get(Service,seed_base['grooming'].id).name = ' '
        elif defect == 'email_case': db.get(User,customer.user_id).email = 'UPPER@petops.example'
        elif defect == 'customer_role_change': db.get(User,customer.user_id).role = Role.ADMIN
        elif defect == 'staff_role_change':
            db.get(User,seed_base['staff1'].id).role = Role.ADMIN
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


@pytest.mark.parametrize('entity', ['pet','customer','service','creator','booking','pet_id_update','service_type_update'])
def test_referenced_records_cannot_be_destroyed_or_relinked(client, seed_base, booking_case, entity):
    _, _, b = booking_case
    with SessionLocal() as db:
        row = db.get(Booking,uuid.UUID(b['id']))
        target = {'pet':db.get(Pet,row.pet_id),'customer':db.get(Customer,row.customer_id),'service':db.get(Service,row.service_id),'creator':db.get(User,row.created_by_user_id),'booking':row}
        if entity == 'pet_id_update': db.get(Pet,row.pet_id).id = uuid.uuid4()
        elif entity == 'service_type_update': db.get(Service,row.service_id).service_type = 'BOARDING'
        else: db.delete(target[entity])
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


def test_postgresql_events_are_append_only(client, booking_case):
    if get_engine().dialect.name != 'postgresql':
        pytest.skip('PostgreSQL trigger guarantee; SQLite is only a surrogate')
    _, _, b = booking_case
    with SessionLocal() as db:
        event = db.scalar(select(BookingEvent).where(BookingEvent.booking_id==uuid.UUID(b['id'])))
        for stmt in (delete(BookingEvent).where(BookingEvent.id==event.id), update(BookingEvent).where(BookingEvent.id==event.id).values(reason='rewritten')):
            with pytest.raises(IntegrityError,match='append-only'): db.execute(stmt)
            db.rollback()


def test_booking_and_initial_event_are_atomic(client, seed_base, monkeypatch):
    import app.services as services
    token, pet = make_customer_with_pet(client)
    original = services.add_event
    def invalid_actor(db, booking, actor, event_type, **kwargs):
        original(db,booking,actor,event_type,**kwargs)
        for row in db.new:
            if isinstance(row,BookingEvent): row.actor_user_id = uuid.uuid4()
    monkeypatch.setattr(services,'add_event',invalid_actor)
    response = client.post('/bookings',headers=bearer(token),json={'pet_id':pet,'service_id':str(seed_base['grooming'].id),'grooming_start':future()})
    assert response.status_code == 409
    assert 'FOREIGN KEY' not in response.text
    assert counts()[3:5] == (0,0)


def test_session_fk_cascades_only_ephemeral_credentials(client, seed_base):
    token = login(client,seed_base['staff2'].email,'DemoPass!123')
    with SessionLocal() as db:
        db.execute(delete(StaffAvailability).where(StaffAvailability.staff_user_id==seed_base['staff2'].id))
        db.delete(db.get(User,seed_base['staff2'].id))
        db.commit()
        assert db.scalar(select(UserSession).where(UserSession.user_id==seed_base['staff2'].id)) is None
    assert client.get('/me',headers=bearer(token)).status_code == 401


@pytest.mark.parametrize('kind,status,operation', [(k,s,o) for k in ('GROOMING','BOARDING') for s in ('SUBMITTED','CONFIRMED') for o in ('cancel','reschedule')])
def test_permitted_customer_changes_for_each_booking_type(client, seed_base, booking_case, kind, status, operation):
    token,pet,b = booking_case
    today = business_today()
    if kind == 'BOARDING':
        b = client.post('/bookings',headers=bearer(token),json={'pet_id':pet,'service_id':str(seed_base['boarding'].id),'boarding_start':(today+timedelta(days=1)).isoformat(),'boarding_end':(today+timedelta(days=2)).isoformat()}).json()
    if status == 'CONFIRMED':
        admin = login(client,seed_base['admin'].email,'DemoPass!123')
        if kind == 'GROOMING':
            assert client.put(f"/admin/bookings/{b['id']}/staff",headers=bearer(admin),json={'staff_user_id':str(seed_base['staff1'].id)}).status_code == 200
        else:
            assert client.put(f"/admin/bookings/{b['id']}/accommodation",headers=bearer(admin),json={'accommodation_id':str(seed_base['unit'].id)}).status_code == 200
        assert client.post(f"/admin/bookings/{b['id']}/status",headers=bearer(admin),json={'status':'CONFIRMED'}).status_code == 200
    before_history = len(client.get(f"/bookings/{b['id']}/history",headers=bearer(token)).json())
    schedule = {'grooming_start':future(5)} if kind == 'GROOMING' else {'boarding_start':(today+timedelta(days=4)).isoformat(),'boarding_end':(today+timedelta(days=5)).isoformat()}
    response = client.post(f"/bookings/{b['id']}/{operation}",headers=bearer(token),json=schedule if operation=='reschedule' else None)
    assert response.status_code == 200
    assert response.json()['status'] == ('CANCELLED' if operation=='cancel' else 'SUBMITTED')
    history = client.get(f"/bookings/{b['id']}/history",headers=bearer(token)).json()
    assert len(history)==before_history+1 and history[-1]['old_status']==status
    assert datetime.fromisoformat(history[-1]['created_at']).tzinfo is not None


@pytest.mark.parametrize('field', ['booking_id','actor_user_id','created_at'])
def test_database_history_rejects_orphan_or_missing_attribution(client, booking_case, field):
    _,_,b = booking_case
    with SessionLocal() as db:
        actor = db.get(Booking,uuid.UUID(b['id'])).created_by_user_id
        values = {'id':uuid.uuid4(),'booking_id':uuid.UUID(b['id']),'actor_user_id':actor,'created_at':datetime.now(timezone.utc),'event_type':'BOOKING_CANCELLED'}
        values[field] = None if field=='created_at' else uuid.uuid4()
        with pytest.raises(IntegrityError): db.execute(BookingEvent.__table__.insert().values(**values))
        db.rollback()


def test_invalid_login_feedback_excludes_submitted_secret(client):
    secret = 'private'*30
    r = client.post('/auth/login',json={'email':'new@petops.example','password':secret})
    assert r.status_code == 422 and secret not in r.text
