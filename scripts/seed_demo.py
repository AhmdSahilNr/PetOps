"""Seed fictional development/demo data only. Never use real customer or business data."""
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
from app.database import SessionLocal
from app.models import Accommodation, Customer, Role, Service, ServiceType, StaffAvailability, User
from app.security import hash_password


def ensure_user(db, email, password, role, display_name=None):
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(email=email, password_hash=hash_password(password), role=role, is_active=True)
    db.add(user); db.flush()
    if role == Role.CUSTOMER:
        db.add(Customer(user_id=user.id, display_name=display_name or "Demo Customer"))
    return user


def main():
    db = SessionLocal()
    try:
        ensure_user(db, "customer.demo@petops.example", "DemoPass!123", Role.CUSTOMER, "Alya Demo")
        staff = ensure_user(db, "staff.demo@petops.example", "DemoPass!123", Role.STAFF)
        admin = ensure_user(db, "admin.demo@petops.example", "DemoPass!123", Role.ADMIN)
        if not db.scalar(select(Service).where(Service.name == "Basic Grooming")):
            db.add(Service(name="Basic Grooming", service_type=ServiceType.GROOMING, is_active=True, duration_minutes=60))
        else:
            service = db.scalar(select(Service).where(Service.name == "Basic Grooming"))
            if service.duration_minutes is None:
                service.duration_minutes = 60
                service.updated_by_user_id = admin.id
        if not db.scalar(select(Service).where(Service.name == "Standard Boarding")):
            db.add(Service(name="Standard Boarding", service_type=ServiceType.BOARDING, is_active=True))
        if not db.scalar(select(Service).where(Service.name == "Inactive Demo Service")):
            db.add(Service(name="Inactive Demo Service", service_type=ServiceType.GROOMING, is_active=False, duration_minutes=60))
        if not db.scalar(select(StaffAvailability.id).where(StaffAvailability.staff_user_id == staff.id)):
            now = datetime.now(timezone.utc)
            db.add(StaffAvailability(staff_user_id=staff.id, starts_at=now, ends_at=now+timedelta(days=30), updated_by_user_id=admin.id))
        if not db.scalar(select(Accommodation.id).where(Accommodation.name == "Fictional Demo Unit")):
            db.add(Accommodation(name="Fictional Demo Unit", category="Fictional", capacity=2, is_active=True,
                notes="Fictional demo configuration; not actual RS Pet House data", updated_by_user_id=admin.id))
        db.commit()
        print("Fictional demo seed complete.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
