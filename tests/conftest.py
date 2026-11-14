from __future__ import annotations

import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from sqlalchemy.engine import make_url

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
os.environ['PETOPS_REMINDER_POLL_SECONDS']='0'  # Explicit jobs/runtime proof exercise scheduling.
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal, reset_database_caches  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Accommodation, Customer, Role, Service, ServiceType, StaffAvailability, User  # noqa: E402
from app.security import hash_password  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database(tmp_path_factory):
    url = os.getenv("PETOPS_TEST_DATABASE_URL")
    if url:
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql" or parsed.host not in {"127.0.0.1", "localhost"} or not (parsed.database or "").endswith("_test"):
            pytest.fail("Use an explicitly disposable loopback PostgreSQL database ending in _test")
    else:
        url = f"sqlite+pysqlite:///{tmp_path_factory.mktemp('petops') / 'test.sqlite3'}"
    os.environ["PETOPS_DATABASE_URL"] = url
    reset_database_caches()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", os.environ["PETOPS_DATABASE_URL"])
    command.upgrade(cfg, "head")
    yield
    reset_database_caches()


@pytest.fixture(autouse=True)
def clean_rows(migrated_database):
    db = SessionLocal()
    try:
        if db.bind.dialect.name == "postgresql":
            db.execute(__import__('sqlalchemy').text("TRUNCATE staff_responsibilities, management_events, notifications, notification_settings, boarding_notes, boarding_stays, grooming_records, boarding_allocations, booking_events, bookings, staff_availability, accommodations, services, pets, customers, user_sessions, users"))
            db.execute(__import__('sqlalchemy').text("INSERT INTO notification_settings(id,enabled) VALUES (1,false)"))
            db.commit()
            yield
            return
        for table in ["staff_responsibilities", "management_events", "notifications", "notification_settings", "boarding_notes", "boarding_stays", "grooming_records", "boarding_allocations", "booking_events", "bookings", "staff_availability", "accommodations", "services", "pets", "customers", "user_sessions", "users"]:
            db.execute(__import__('sqlalchemy').text(f"DELETE FROM {table}"))
        db.commit()
        yield
    finally:
        db.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seed_base():
    db = SessionLocal()
    try:
        admin = User(email="admin.demo@petops.example", password_hash=hash_password("DemoPass!123"), role=Role.ADMIN, is_active=True)
        staff1 = User(email="staff.one@petops.example", password_hash=hash_password("DemoPass!123"), role=Role.STAFF, is_active=True)
        staff2 = User(email="staff.two@petops.example", password_hash=hash_password("DemoPass!123"), role=Role.STAFF, is_active=True)
        db.add_all([admin, staff1, staff2]); db.flush()
        grooming = Service(name="Basic Grooming", service_type=ServiceType.GROOMING, is_active=True, duration_minutes=60)
        boarding = Service(name="Standard Boarding", service_type=ServiceType.BOARDING, is_active=True)
        inactive = Service(name="Inactive Grooming", service_type=ServiceType.GROOMING, is_active=False, duration_minutes=60)
        now = datetime.now(timezone.utc)
        # Broad fictional fixture windows are test data, not real Staff shifts.
        windows = [StaffAvailability(staff_user_id=s.id, starts_at=now-timedelta(days=2),
            ends_at=now+timedelta(days=4000), updated_by_user_id=admin.id) for s in (staff1,staff2)]
        unit = Accommodation(name="Fictional Test Unit", category="Fictional", capacity=10, is_active=True, updated_by_user_id=admin.id)
        db.add_all([grooming, boarding, inactive, unit, *windows]); db.commit()
        return {"admin": admin, "staff1": staff1, "staff2": staff2, "grooming": grooming, "boarding": boarding, "inactive": inactive, "unit": unit}
    finally:
        db.close()


def register_customer(client, email="customer.one@petops.example", name="Customer One"):
    r = client.post("/auth/register", json={"email": email, "password": "CustomerPass!123", "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def login(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]
