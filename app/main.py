from __future__ import annotations

from uuid import UUID
from pathlib import Path
import hashlib
import os

from fastapi import Depends, FastAPI, HTTPException, Response, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .database import get_db
from .models import Booking, BookingEvent, BookingStatus, Customer, Pet, Role, Service, User, UserSession
from .schemas import AdminStatusIn, BookingCreateIn, LoginIn, PasswordChangeIn, PetIn, ProfileUpdateIn, RegisterIn, RescheduleIn
from .security import get_current_user, hash_password, issue_session, normalize_email, require_roles, verify_password, _extract_token
from .services import admin_change_status, cancel_booking, create_booking, customer_for_user, reschedule_booking, utc_iso
from .resource_routes import router as resource_router, allocation_view
from .availability import current_allocations
from .views import booking_view, event_view
from .grooming_routes import router as grooming_router
from .boarding_routes import router as boarding_router
from .notifications import router as notification_router, lifespan
from .management import router as management_router
from .dashboard import router as dashboard_router
from .operations import router as operations_router
from .projections import customer_booking, customer_event

app = FastAPI(title="PetOps Technical Foundation", version="0.1.0", lifespan=lifespan)
app.include_router(resource_router)
app.include_router(grooming_router)
app.include_router(boarding_router)
app.include_router(notification_router)
app.include_router(management_router)
app.include_router(dashboard_router)
app.include_router(operations_router)
STATIC = Path(__file__).with_name("static")
SHELL = Path(__file__).with_name("templates") / "index.html"


def compute_asset_version() -> str:
    """Content hash of every static file: any change to any asset changes the version."""
    digest = hashlib.sha256()
    for path in sorted(p for p in STATIC.rglob("*") if p.is_file()):
        digest.update(path.relative_to(STATIC).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


ASSET_VERSION = compute_asset_version()


class RevalidatedStatic(StaticFiles):
    """Browsers must revalidate (ETag/304) so nested ES-module imports can never be stale."""
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


app.mount("/static", RevalidatedStatic(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def demo_page():
    html = SHELL.read_text(encoding="utf-8").replace("{{ASSET_VERSION}}", ASSET_VERSION)
    return Response(content=html, media_type="text/html; charset=utf-8", headers={
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin"})


@app.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(_extract_token(request).encode()).hexdigest()
    db.execute(delete(UserSession).where(UserSession.token_hash == token_hash, UserSession.user_id == user.id))
    db.commit()
    response.status_code = 204
    response.delete_cookie("petops_session", httponly=True, samesite="strict", secure=os.getenv("PETOPS_ENV") == "production")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Pydantic's default includes submitted values, including passwords.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
        for e in exc.errors()
    ]})


@app.exception_handler(StaleDataError)
async def stale_booking(request: Request, exc: StaleDataError):
    return JSONResponse(status_code=409, content={"detail": "Booking changed concurrently; reload before retrying"})


@app.exception_handler(IntegrityError)
async def integrity_conflict(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"detail": "Operation conflicts with existing records or required data relationships"})


@app.exception_handler(OperationalError)
async def database_operation_error(request: Request, exc: OperationalError):
    code = getattr(exc.orig, "sqlstate", None)
    if code in {"40001", "40P01"}:
        return JSONResponse(status_code=409, content={"detail": "Concurrent resource change; reload and retry"})
    return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})


def user_view(user: User):
    return {"id": str(user.id), "email": user.email, "role": user.role.value, "display_name": user.display_name,"is_active":user.is_active}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    email = normalize_email(str(payload.email))
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Account already exists")
    user = User(email=email, password_hash=hash_password(payload.password), role=Role.CUSTOMER)
    try:
        db.add(user)
        db.flush()
        db.add(Customer(user_id=user.id, display_name=payload.display_name))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account already exists")
    return user_view(user)


@app.post("/auth/login")
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    # Share the password-change row lock (PUT /account/password): a change committed after this
    # login revokes its session too; an old password cannot create a later session.
    user = db.scalar(select(User).where(User.email == normalize_email(str(payload.email))).with_for_update())
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = issue_session(db, user)
    response.set_cookie("petops_session", token, httponly=True, samesite="strict", secure=os.getenv("PETOPS_ENV") == "production", max_age=43200)
    return {"token": token, "user": user_view(user)}


@app.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_view(user)


@app.get("/customer/profile")
def get_profile(user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    return {"id": str(c.id), "display_name": c.display_name, "email": user.email}


@app.put("/customer/profile")
def update_profile(payload: ProfileUpdateIn, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    c.display_name = payload.display_name.strip()
    db.commit(); db.refresh(c)
    return {"id": str(c.id), "display_name": c.display_name}


@app.get("/pets")
def list_pets(user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    return [{"id": str(p.id), "name": p.name, "is_active": p.is_active} for p in db.scalars(select(Pet).where(Pet.customer_id == c.id).order_by(Pet.name)).all()]


@app.post("/pets", status_code=201)
def create_pet(payload: PetIn, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    p = Pet(customer_id=c.id, name=payload.name.strip())
    db.add(p); db.commit(); db.refresh(p)
    return {"id": str(p.id), "name": p.name}


@app.put("/pets/{pet_id}")
def update_pet(pet_id: UUID, payload: PetIn, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    p = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.customer_id == c.id))
    if not p: raise HTTPException(status_code=404, detail="Pet not found")
    p.name = payload.name.strip(); db.commit(); db.refresh(p)
    return {"id": str(p.id), "name": p.name}


@app.delete("/pets/{pet_id}", status_code=204)
def delete_pet(pet_id: UUID, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    p = db.scalar(select(Pet).where(Pet.id == pet_id, Pet.customer_id == c.id))
    if not p: raise HTTPException(status_code=404, detail="Pet not found")
    db.delete(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(status_code=409, detail="Pet with booking history cannot be deleted")
    return Response(status_code=204)


@app.get("/services")
def active_services(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Service).where(Service.is_active.is_(True)).order_by(Service.service_type, Service.display_order, Service.name, Service.id)).all()
    return [{"id": str(s.id), "name": s.name, "service_type": s.service_type.value, "duration_minutes": s.duration_minutes, "display_order": s.display_order} for s in rows if s.service_type.value != "GROOMING" or s.duration_minutes is not None]


@app.post("/bookings", status_code=201)
def create_customer_booking(payload: BookingCreateIn, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    return customer_booking(booking_view(create_booking(db, c, user, **payload.model_dump())))


@app.get("/bookings")
def list_customer_bookings(user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    return [customer_booking(booking_view(b)) for b in db.scalars(select(Booking).where(Booking.customer_id == c.id).order_by(Booking.created_at.desc())).all()]


@app.get("/bookings/{booking_id}")
def get_customer_booking(booking_id: UUID, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    b = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.customer_id == c.id))
    if not b: raise HTTPException(status_code=404, detail="Booking not found")
    return customer_booking(booking_view(b))


@app.post("/bookings/{booking_id}/reschedule")
def reschedule_customer_booking(booking_id: UUID, payload: RescheduleIn, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    b = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.customer_id == c.id).with_for_update())
    if not b: raise HTTPException(status_code=404, detail="Booking not found")
    return customer_booking(booking_view(reschedule_booking(db, b, user, **payload.model_dump())))


@app.post("/bookings/{booking_id}/cancel")
def cancel_customer_booking(booking_id: UUID, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    b = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.customer_id == c.id).with_for_update())
    if not b: raise HTTPException(status_code=404, detail="Booking not found")
    return customer_booking(booking_view(cancel_booking(db, b, user)))


@app.get("/bookings/{booking_id}/history")
def customer_booking_history(booking_id: UUID, user: User = Depends(require_roles(Role.CUSTOMER)), db: Session = Depends(get_db)):
    c = customer_for_user(db, user)
    b = db.scalar(select(Booking).where(Booking.id == booking_id, Booking.customer_id == c.id))
    if not b: raise HTTPException(status_code=404, detail="Booking not found")
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == b.id).order_by(BookingEvent.created_at,BookingEvent.id)).all()
    return [customer_event(event_view(e)) for e in events]


@app.get("/staff/bookings/{booking_id}")
def staff_get_assigned_booking(booking_id: UUID, user: User = Depends(require_roles(Role.STAFF)), db: Session = Depends(get_db)):
    # C03-M01: same responsibility read scope as the canonical /grooming and /boarding detail routes (PS-03),
    # not the assignment snapshot, so a currently responsible Staff member keeps read access until a
    # future-effective handover takes effect. Read-only; mutation authority is unchanged.
    from .responsibilities import staff_scope
    b = db.scalar(select(Booking).where(Booking.id == booking_id, staff_scope(user.id)))
    if not b: raise HTTPException(status_code=404, detail="Assigned booking not found")
    return {**booking_view(b), "accommodation_allocations": [allocation_view(a) for a in current_allocations(db, b.id)]}


@app.get("/admin/bookings/{booking_id}")
def admin_get_booking(booking_id: UUID, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    b = db.get(Booking, booking_id)
    if not b: raise HTTPException(status_code=404, detail="Booking not found")
    return booking_view(b)


@app.post("/admin/bookings/{booking_id}/status")
def admin_status(booking_id: UUID, payload: AdminStatusIn, user: User = Depends(require_roles(Role.ADMIN)), db: Session = Depends(get_db)):
    b = db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update())
    if not b: raise HTTPException(status_code=404, detail="Booking not found")
    return booking_view(admin_change_status(db, b, user, payload.status))

@app.put("/account")
def update_own_staff_account(payload:ProfileUpdateIn,user:User=Depends(require_roles(Role.STAFF)),db:Session=Depends(get_db)):
    user.display_name=payload.display_name;db.commit();return user_view(user)

@app.put("/account/password", status_code=204)
def change_own_staff_password(payload: PasswordChangeIn, request: Request, user: User = Depends(require_roles(Role.STAFF)), db: Session = Depends(get_db)):
    # Same row lock as /auth/login: a concurrent login with the old password either finishes first (its session
    # is revoked below) or waits and then fails against the new hash. populate_existing re-reads the locked row.
    locked = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if not verify_password(payload.current_password, locked.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    locked.password_hash = hash_password(payload.new_password)
    current = hashlib.sha256(_extract_token(request).encode()).hexdigest()
    db.execute(delete(UserSession).where(UserSession.user_id == locked.id, UserSession.token_hash != current))
    db.commit()
    return Response(status_code=204)

@app.post("/pets/{pet_id}/archive")
def archive_pet(pet_id:UUID,user:User=Depends(require_roles(Role.CUSTOMER)),db:Session=Depends(get_db)):
    c=customer_for_user(db,user);p=db.scalar(select(Pet).where(Pet.id==pet_id,Pet.customer_id==c.id))
    if not p:raise HTTPException(404,"Pet not found")
    p.is_active=False;db.commit();return {"id":str(p.id),"name":p.name,"is_active":False}
