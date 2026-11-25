"""Supervisor corrections after the FYP1 presentation (Nov 2026): Staff change their own password;
Admin cannot change an existing Staff password (Option A, strict)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.database import SessionLocal
from app.models import ManagementEvent, User, UserSession
from tests.conftest import login
from tests.test_vertical_slice import bearer
from tests.test_slice2 import case
from tests.test_slice5 import call

OLD, NEW = 'DemoPass!123', 'StaffOwnNew!456'


def change(c, token, body):
    return c['client'].put('/account/password', headers=bearer(token), json=body)


def stored_hash(user_id):
    with SessionLocal() as db:
        return db.scalar(select(User.password_hash).where(User.id == user_id))


def test_staff_changes_own_password_and_other_sessions_are_revoked(case):
    c = case; staff = c['seed']['staff1']; before = stored_hash(staff.id)
    current = login(c['client'], staff.email, OLD); other = login(c['client'], staff.email, OLD)
    r = change(c, current, {'current_password': OLD, 'new_password': NEW})
    assert r.status_code == 204 and r.content == b''
    assert c['client'].get('/me', headers=bearer(current)).status_code == 200
    assert c['client'].get('/me', headers=bearer(other)).status_code == 401
    assert c['client'].post('/auth/login', json={'email': staff.email, 'password': OLD}).status_code == 401
    login(c['client'], staff.email, NEW)
    after = stored_hash(staff.id)
    assert after != before and after.startswith('scrypt$') and NEW not in after


def test_wrong_current_password_changes_nothing(case):
    c = case; staff = c['seed']['staff1']; before = stored_hash(staff.id)
    current = login(c['client'], staff.email, OLD); other = login(c['client'], staff.email, OLD)
    r = change(c, current, {'current_password': 'NotMyPassword!1', 'new_password': NEW})
    assert r.status_code == 400 and r.json() == {'detail': 'Current password is incorrect'}
    assert 'NotMyPassword' not in r.text and NEW not in r.text
    assert stored_hash(staff.id) == before
    assert c['client'].get('/me', headers=bearer(other)).status_code == 200
    login(c['client'], staff.email, OLD)


@pytest.mark.parametrize('body', [
    {'current_password': OLD, 'new_password': 'short9!'},
    {'current_password': OLD, 'new_password': 'x' * 129},
    {'current_password': OLD, 'new_password': OLD},
    {'current_password': '', 'new_password': NEW},
    {'new_password': NEW},
    {'current_password': OLD, 'new_password': NEW, 'role': 'ADMIN'},
])
def test_password_change_validation_never_echoes_values(case, body):
    c = case; staff = c['seed']['staff1']; before = stored_hash(staff.id)
    current = login(c['client'], staff.email, OLD); other = login(c['client'], staff.email, OLD)
    r = change(c, current, body)
    assert r.status_code == 422
    assert all(set(e) == {'loc', 'msg', 'type'} for e in r.json()['detail'])
    for value in body.values():
        if len(value) >= 4: assert value not in r.text
    assert stored_hash(staff.id) == before
    assert c['client'].get('/me', headers=bearer(other)).status_code == 200


def test_only_signed_in_staff_can_change_a_password(case):
    c = case; body = {'current_password': OLD, 'new_password': NEW}
    with TestClient(app) as anonymous:  # fresh client: the shared one carries the last sign-in's cookie
        assert anonymous.put('/account/password', json=body).status_code == 401
    assert c['client'].put('/account/password', headers=c['owner'], json=body).status_code == 403
    assert c['client'].put('/account/password', headers=c['admin'], json=body).status_code == 403
    login(c['client'], c['seed']['admin'].email, OLD)


def test_admin_cannot_change_an_existing_staff_password(case):
    c = case; staff = c['seed']['staff2']; before = stored_hash(staff.id)
    session = login(c['client'], staff.email, OLD)
    r = c['client'].put(f"/admin/staff/{staff.id}", headers=c['admin'],
                        json={'email': staff.email, 'is_active': True, 'password': 'AdminChosen!789'})
    assert r.status_code == 422 and 'AdminChosen' not in r.text
    assert stored_hash(staff.id) == before
    assert c['client'].get('/me', headers=bearer(session)).status_code == 200
    assert c['client'].post('/auth/login', json={'email': staff.email, 'password': 'AdminChosen!789'}).status_code == 401
    assert call(c, 'GET', '/admin/management-history') == []
    # Ordinary account maintenance still works and does not sign the person out.
    call(c, 'PUT', f"/admin/staff/{staff.id}", {'email': staff.email, 'is_active': True, 'display_name': 'Staff Two'})
    assert c['client'].get('/me', headers=bearer(session)).status_code == 200


def test_no_other_account_endpoint_can_set_a_password(case):
    c = case; staff = c['seed']['staff1']; before = stored_hash(staff.id)
    session = login(c['client'], staff.email, OLD)
    # Profile endpoints accept only a display name (extra fields are rejected, not ignored).
    r = c['client'].put('/account', headers=bearer(session), json={'display_name': 'Staff One', 'password': 'Smuggled!12345'})
    assert r.status_code == 422 and 'Smuggled' not in r.text
    r = c['client'].put('/customer/profile', headers=c['owner'], json={'display_name': 'Owner', 'password': 'Smuggled!12345'})
    assert r.status_code == 422 and 'Smuggled' not in r.text
    # Admin cannot "re-create" an existing Staff account to overwrite its credentials.
    call(c, 'POST', '/admin/staff', {'email': staff.email, 'password': 'Overwrite!12345'}, code=409)
    r = c['client'].put(f"/admin/staff/{staff.id}", headers=c['admin'], json={'email': staff.email, 'is_active': True, 'password_hash': 'x'})
    assert r.status_code == 422
    assert stored_hash(staff.id) == before
    assert c['client'].post('/auth/login', json={'email': staff.email, 'password': 'Overwrite!12345'}).status_code == 401
    login(c['client'], staff.email, OLD)


def test_password_change_keeps_the_same_staff_identity_and_history(case):
    from tests.test_slice2 import grooming, assign, confirm
    c = case; staff = c['seed']['staff1']; b = grooming(c); assign(c, b); confirm(c, b)
    session = login(c['client'], staff.email, OLD)
    before = c['client'].get('/me', headers=bearer(session)).json()
    assert change(c, session, {'current_password': OLD, 'new_password': NEW}).status_code == 204
    after = c['client'].get('/me', headers=bearer(session)).json()
    assert after == before  # same id, email, role, name and active status
    detail = c['client'].get(f"/admin/bookings/{b['id']}", headers=c['admin']).json()
    assert detail['assigned_staff_user_id'] == str(staff.id)  # assigned work and history still belong to the same account


def test_self_change_leaves_no_secret_in_records(case):
    c = case; staff = c['seed']['staff1']
    current = login(c['client'], staff.email, OLD)
    assert change(c, current, {'current_password': OLD, 'new_password': NEW}).status_code == 204
    with SessionLocal() as db:
        events = db.scalars(select(ManagementEvent)).all()
        tokens = db.scalars(select(UserSession.token_hash).where(UserSession.user_id == staff.id)).all()
    assert events == []  # self-service changes are not Admin management events
    assert len(tokens) == 1 and current not in tokens  # only the hashed current session remains
    assert not any(x in str(call(c, 'GET', '/admin/management-history')) for x in (OLD, NEW))
