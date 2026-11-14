from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, get_engine
from app.main import app
from app.models import Booking, BookingEvent, BookingStatus, Customer, Pet, Service, User
from tests.conftest import login, register_customer


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def make_customer_with_pet(client, email="customer.one@petops.example", name="Customer One"):
    register_customer(client, email, name)
    token = login(client, email, "CustomerPass!123")
    pet = client.post("/pets", json={"name": "Milo"}, headers=bearer(token))
    assert pet.status_code == 201
    return token, pet.json()["id"]


def service_id(name):
    db = SessionLocal()
    try:
        return str(db.scalar(select(Service).where(Service.name == name)).id)
    finally:
        db.close()


def test_successful_and_invalid_login(client, seed_base):
    register_customer(client)
    ok = client.post("/auth/login", json={"email": "CUSTOMER.ONE@petops.example", "password": "CustomerPass!123"})
    assert ok.status_code == 200
    assert ok.json()["user"]["role"] == "CUSTOMER"
    bad = client.post("/auth/login", json={"email": "customer.one@petops.example", "password": "wrong-password"})
    assert bad.status_code == 401


def test_protected_route_denial_and_cross_role_denial(client, seed_base):
    assert client.get("/customer/profile").status_code == 401
    staff_token = login(client, "staff.one@petops.example", "DemoPass!123")
    assert client.get("/customer/profile", headers=bearer(staff_token)).status_code == 403
    register_customer(client)
    customer_token = login(client, "customer.one@petops.example", "CustomerPass!123")
    assert client.get(f"/admin/bookings/{uuid.uuid4()}", headers=bearer(customer_token)).status_code == 403


def test_cross_customer_pet_and_booking_denial(client, seed_base):
    token1, pet1 = make_customer_with_pet(client, "customer.one@petops.example", "One")
    register_customer(client, "customer.two@petops.example", "Two")
    token2 = login(client, "customer.two@petops.example", "CustomerPass!123")
    assert client.put(f"/pets/{pet1}", json={"name": "Stolen"}, headers=bearer(token2)).status_code == 404
    payload = {"pet_id": pet1, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    assert client.post("/bookings", json=payload, headers=bearer(token2)).status_code == 404


def test_customer_pet_referential_integrity_database_constraint(client, seed_base):
    token1, pet1 = make_customer_with_pet(client, "customer.one@petops.example", "One")
    register_customer(client, "customer.two@petops.example", "Two")
    db = SessionLocal()
    try:
        c2 = db.scalar(select(Customer).join(User, Customer.user_id == User.id).where(User.email == "customer.two@petops.example"))
        b = Booking(customer_id=c2.id, pet_id=uuid.UUID(pet1), service_id=uuid.UUID(service_id("Basic Grooming")), booking_type="GROOMING", status=BookingStatus.SUBMITTED, grooming_start=datetime.now(timezone.utc)+timedelta(days=2), grooming_duration_minutes=60, created_by_user_id=c2.user_id)
        db.add(b)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()


def test_valid_invalid_booking_creation_and_active_services(client, seed_base):
    token, pet_id = make_customer_with_pet(client)
    services = client.get("/services", headers=bearer(token))
    assert services.status_code == 200
    names = {x["name"] for x in services.json()}
    assert "Basic Grooming" in names and "Standard Boarding" in names and "Inactive Grooming" not in names

    grooming = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token))
    assert grooming.status_code == 201
    assert grooming.json()["status"] == "SUBMITTED"
    boarding = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Standard Boarding"), "boarding_start": (date.today()+timedelta(days=2)).isoformat(), "boarding_end": (date.today()+timedelta(days=4)).isoformat()}, headers=bearer(token))
    assert boarding.status_code == 201
    inactive = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Inactive Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token))
    assert inactive.status_code == 422
    invalid_dates = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Standard Boarding"), "boarding_start": (date.today()+timedelta(days=4)).isoformat(), "boarding_end": (date.today()+timedelta(days=3)).isoformat()}, headers=bearer(token))
    assert invalid_dates.status_code == 422


def test_invalid_status_transition_and_role_control(client, seed_base):
    token, pet_id = make_customer_with_pet(client)
    booking = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token)).json()
    admin_token = login(client, "admin.demo@petops.example", "DemoPass!123")
    invalid = client.post(f"/admin/bookings/{booking['id']}/status", json={"status":"COMPLETED"}, headers=bearer(admin_token))
    assert invalid.status_code == 409
    blocked = client.post(f"/admin/bookings/{booking['id']}/status", json={"status":"CONFIRMED"}, headers=bearer(admin_token))
    assert blocked.status_code == 409 and "BR-002" in blocked.json()["detail"]
    good = client.post(f"/admin/bookings/{booking['id']}/status", json={"status":"REJECTED"}, headers=bearer(admin_token))
    assert good.status_code == 200 and good.json()["status"] == "REJECTED"
    second = client.post(f"/admin/bookings/{booking['id']}/status", json={"status":"REJECTED"}, headers=bearer(admin_token))
    assert second.status_code == 409


def test_permitted_and_prohibited_reschedule_cancel_with_history(client, seed_base):
    token, pet_id = make_customer_with_pet(client)
    booking = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token)).json()
    admin_token = login(client, "admin.demo@petops.example", "DemoPass!123")
    assert client.put(f"/admin/bookings/{booking['id']}/staff", json={"staff_user_id":str(seed_base['staff1'].id)}, headers=bearer(admin_token)).status_code == 200
    assert client.post(f"/admin/bookings/{booking['id']}/status", json={"status":"CONFIRMED"}, headers=bearer(admin_token)).status_code == 200
    res = client.post(f"/bookings/{booking['id']}/reschedule", json={"grooming_start": (datetime.now(timezone.utc)+timedelta(days=3)).isoformat()}, headers=bearer(token))
    assert res.status_code == 200 and res.json()["status"] == "SUBMITTED"
    history = client.get(f"/bookings/{booking['id']}/history", headers=bearer(token))
    types = [e["event_type"] for e in history.json()]
    assert types == ["BOOKING_SUBMITTED", "STAFF_ASSIGNED", "STATUS_CHANGED", "BOOKING_RESCHEDULED"]
    res_event = history.json()[-1]
    assert res_event["old_status"] == "CONFIRMED" and res_event["new_status"] == "SUBMITTED"
    assert res_event["old_schedule"] != res_event["new_schedule"]

    cancel = client.post(f"/bookings/{booking['id']}/cancel", headers=bearer(token))
    assert cancel.status_code == 200 and cancel.json()["status"] == "CANCELLED"
    again = client.post(f"/bookings/{booking['id']}/reschedule", json={"grooming_start": (datetime.now(timezone.utc)+timedelta(days=5)).isoformat()}, headers=bearer(token))
    assert again.status_code == 409


def test_staff_unassigned_record_denial_and_assigned_access(client, seed_base):
    token, pet_id = make_customer_with_pet(client)
    booking = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token)).json()
    staff1 = login(client, "staff.one@petops.example", "DemoPass!123")
    staff2 = login(client, "staff.two@petops.example", "DemoPass!123")
    assert client.get(f"/staff/bookings/{booking['id']}", headers=bearer(staff1)).status_code == 404
    admin_token = login(client, "admin.demo@petops.example", "DemoPass!123")
    assert client.put(f"/admin/bookings/{booking['id']}/staff", json={"staff_user_id":str(seed_base['staff1'].id)}, headers=bearer(admin_token)).status_code == 200
    assert client.get(f"/staff/bookings/{booking['id']}", headers=bearer(staff1)).status_code == 200
    assert client.get(f"/staff/bookings/{booking['id']}", headers=bearer(staff2)).status_code == 404


def test_pet_with_booking_cannot_be_deleted_and_history_is_preserved(client, seed_base):
    token, pet_id = make_customer_with_pet(client)
    booking = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token)).json()
    assert client.delete(f"/pets/{pet_id}", headers=bearer(token)).status_code == 409
    db = SessionLocal()
    try:
        b = db.get(Booking, uuid.UUID(booking["id"]))
        assert db.scalar(select(BookingEvent).where(BookingEvent.booking_id == b.id)) is not None
    finally:
        db.close()


def test_persistence_after_client_restart(client, seed_base):
    token, pet_id = make_customer_with_pet(client)
    booking = client.post("/bookings", json={"pet_id": pet_id, "service_id": service_id("Basic Grooming"), "grooming_start": (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}, headers=bearer(token)).json()
    get_engine().dispose()
    with TestClient(app) as restarted:
        new_token = login(restarted, "customer.one@petops.example", "CustomerPass!123")
        got = restarted.get(f"/bookings/{booking['id']}", headers=bearer(new_token))
        assert got.status_code == 200 and got.json()["id"] == booking["id"]
