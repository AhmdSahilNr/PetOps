"""Slice 4: bounded Boarding operations; no invented care sub-features."""
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import (Accommodation, BoardingAllocation, BoardingNote, BoardingStay,
    Booking, BookingEvent, BookingStatus, Customer, Pet, Role, Service, ServiceType, User, utcnow)
from .availability import current_allocations
from .resource_routes import allocation_view
from .schemas import BoardingNoteIn, InputModel
from .security import get_current_user, require_roles
from .services import add_event, business_today, customer_for_user, utc_iso
from .views import booking_view, event_view

router=APIRouter(prefix="/boarding", tags=["Boarding"])
operators=require_roles(Role.STAFF, Role.ADMIN)


def scoped_query(db, user):
    query=select(Booking).where(Booking.booking_type==ServiceType.BOARDING)
    if user.role==Role.CUSTOMER:
        query=query.where(Booking.customer_id==customer_for_user(db,user).id)
    elif user.role==Role.STAFF:
        from .responsibilities import staff_scope
        query=query.where(staff_scope(user.id))
    elif user.role!=Role.ADMIN:
        raise HTTPException(403,"Action not permitted for this role")
    return query


def find_work(db,user,booking_id,lock=False):
    query=scoped_query(db,user).where(Booking.id==booking_id)
    b=db.scalar(query.with_for_update() if lock else query)
    if not b:raise HTTPException(404,"Permitted Boarding booking not found")
    return b


def stay_view(s):
    if s is None:return None
    result={"id":str(s.id),"booking_id":str(s.booking_id),"allocation_id":str(s.allocation_id)}
    for step in ("checked_in","stay_started","checked_out","completed"):
        actor=getattr(s,step+"_by_user_id")
        result[step+"_by_user_id"]=str(actor) if actor else None
        result[step+"_at"]=utc_iso(getattr(s,step+"_at"))
    return result


def note_view(n):
    return {"id":str(n.id),"stay_id":str(n.stay_id),"event_id":str(n.event_id),
        "note":n.note,"actor_user_id":str(n.actor_user_id),"created_at":utc_iso(n.created_at)}


def detail(db,b):
    s=db.scalar(select(BoardingStay).where(BoardingStay.booking_id==b.id))
    notes=db.scalars(select(BoardingNote).where(BoardingNote.stay_id==s.id).order_by(BoardingNote.created_at,BoardingNote.id)).all() if s else []
    events=db.scalars(select(BookingEvent).where(BookingEvent.booking_id==b.id).order_by(BookingEvent.created_at,BookingEvent.id)).all()
    allocations=db.scalars(select(BoardingAllocation).where(BoardingAllocation.booking_id==b.id).order_by(BoardingAllocation.created_at)).all()
    from .responsibilities import rows_for,view
    return {"responsibilities":[view(db,row) for row in rows_for(db,b.id)],"booking":booking_view(b),"customer_name":db.get(Customer,b.customer_id).display_name,
        "pet_name":db.get(Pet,b.pet_id).name,"service_name":db.get(Service,b.service_id).name,
        "boarding_stay":stay_view(s),"stay_notes":[note_view(n) for n in notes],
        "allocation_history":[{**allocation_view(a),"name":db.get(Accommodation,a.accommodation_id).name,
            "released_by_user_id":str(a.released_by_user_id) if a.released_by_user_id else None} for a in allocations],
        "history":[event_view(e) for e in events]}


@router.get("/bookings")
def work_list(user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return [{**booking_view(b),"pet_name":db.get(Pet,b.pet_id).name,"service_name":db.get(Service,b.service_id).name,"customer_name":db.get(Customer,b.customer_id).display_name}
        for b in db.scalars(scoped_query(db,user).order_by(Booking.created_at.desc()))]


@router.get("/bookings/{booking_id}")
def work_detail(booking_id:UUID,user:User=Depends(get_current_user),db:Session=Depends(get_db)):
    return detail(db,find_work(db,user,booking_id))


@router.get("/staff-options")
def assignment_accounts(user:User=Depends(require_roles(Role.ADMIN)),db:Session=Depends(get_db)):
    # Optional duty window still passes the existing assignment eligibility rules.
    return [{"id":str(u.id),"email":u.email,"display_name":u.display_name} for u in db.scalars(select(User).where(User.role==Role.STAFF,User.is_active.is_(True)).order_by(User.email))]


def transition(db,user,booking_id,source,target,step,event,commit=True):
    b=find_work(db,user,booking_id,lock=True)
    if b.status!=source:raise HTTPException(409,"This action is unavailable for the current booking status")
    from .responsibilities import current_staff
    legacy_departure=b.status==BookingStatus.CHECKED_OUT and b.assigned_staff_user_id==user.id
    if user.role==Role.STAFF and current_staff(db,b)!=user.id and not legacy_departure:raise HTTPException(403,"Only currently responsible Staff can record stay actions")
    if step=="checked_in":
        if not b.boarding_start<=business_today()<b.boarding_end:
            raise HTTPException(409,"Check-in is permitted only within the reserved Boarding dates")
        allocations=current_allocations(db,b.id)
        if len(allocations)!=1:raise HTTPException(409,"Matching accommodation allocation required for check-in")
        a=allocations[0];unit=db.get(Accommodation,a.accommodation_id)
        if not unit or not unit.is_active or a.starts_on!=b.boarding_start or a.ends_on!=b.boarding_end:
            raise HTTPException(409,"Matching active accommodation required for check-in")
        occupied=db.scalar(select(func.count()).select_from(BoardingStay).join(BoardingAllocation,BoardingStay.allocation_id==BoardingAllocation.id)
            .where(BoardingAllocation.accommodation_id==unit.id,BoardingStay.checked_out_at.is_(None)))
        if occupied>=unit.capacity:raise HTTPException(409,"Accommodation is physically full; check-out must release occupied places")
        s=BoardingStay(id=uuid4(),booking_id=b.id,allocation_id=a.id,checked_in_by_user_id=user.id,checked_in_at=utcnow())
    else:
        s=db.scalar(select(BoardingStay).where(BoardingStay.booking_id==b.id))
        if not s:raise HTTPException(409,"Retained Boarding stay record required")
    now=s.checked_in_at if step=="checked_in" else utcnow()
    b.status=target
    db.flush()
    if step=="checked_in":
        s.stay_started_at,s.stay_started_by_user_id=now,user.id
        db.add(s)
    else:
        setattr(s,step+"_by_user_id",user.id);setattr(s,step+"_at",now)
    if step=="checked_out":
        s.completed_at,s.completed_by_user_id=now,user.id
        a=db.get(BoardingAllocation,s.allocation_id)
        if not a or a.released_at:raise HTTPException(409,"Current accommodation allocation required for check-out")
        a.released_at,a.released_by_user_id=now,user.id
    db.flush()
    add_event(db,b,user,event,old_status=source,new_status=target,
        old_assigned_staff_user_id=b.assigned_staff_user_id,created_at=now,
        details={"boarding_stay_id":str(s.id),"allocation_id":str(s.allocation_id)})
    if step=="checked_out":
        add_event(db,b,user,"BOARDING_COMPLETED",old_status=source,new_status=target,created_at=now,
            details={"boarding_stay_id":str(s.id),"automatic_with_checkout":True})
    if commit:db.commit()
    return detail(db,b)


@router.post("/bookings/{booking_id}/check-in")
def check_in(booking_id:UUID,payload:InputModel,user:User=Depends(operators),db:Session=Depends(get_db)):
    return transition(db,user,booking_id,BookingStatus.CONFIRMED,BookingStatus.STAYING,"checked_in","BOARDING_CHECKED_IN")


@router.post("/bookings/{booking_id}/start-stay", deprecated=True)
def start_stay(booking_id:UUID,payload:InputModel,user:User=Depends(operators),db:Session=Depends(get_db)):
    return transition(db,user,booking_id,BookingStatus.CHECKED_IN,BookingStatus.STAYING,"stay_started","BOARDING_STAY_STARTED")


@router.post("/bookings/{booking_id}/check-out")
def check_out(booking_id:UUID,payload:InputModel,user:User=Depends(operators),db:Session=Depends(get_db)):
    b=find_work(db,user,booking_id,lock=True)
    # A historical arrival can exit through the same single checkout action.
    if b.status==BookingStatus.CHECKED_IN:
        transition(db,user,booking_id,BookingStatus.CHECKED_IN,BookingStatus.STAYING,"stay_started","BOARDING_STAY_STARTED",commit=False)
    return transition(db,user,booking_id,BookingStatus.STAYING,BookingStatus.COMPLETED,"checked_out","BOARDING_CHECKED_OUT")


@router.post("/bookings/{booking_id}/complete", deprecated=True)
def complete_stay(booking_id:UUID,payload:InputModel,user:User=Depends(operators),db:Session=Depends(get_db)):
    return transition(db,user,booking_id,BookingStatus.CHECKED_OUT,BookingStatus.COMPLETED,"completed","BOARDING_COMPLETED")


@router.post("/bookings/{booking_id}/notes",status_code=201)
def add_stay_note(booking_id:UUID,payload:BoardingNoteIn,user:User=Depends(operators),db:Session=Depends(get_db)):
    b=find_work(db,user,booking_id,lock=True)
    if b.status not in {BookingStatus.CHECKED_IN,BookingStatus.STAYING}:
        raise HTTPException(409,"Stay updates require an active Boarding stay")
    from .responsibilities import current_staff
    if user.role==Role.STAFF and current_staff(db,b)!=user.id:raise HTTPException(403,"Only current responsibility may add stay updates")
    s=db.scalar(select(BoardingStay).where(BoardingStay.booking_id==b.id))
    if not s:raise HTTPException(409,"Active Boarding stay record required")
    now=utcnow();nid,eid=uuid4(),uuid4()
    db.add(BookingEvent(id=eid,booking_id=b.id,event_type="BOARDING_STAY_UPDATED",old_status=b.status,new_status=b.status,
        actor_user_id=user.id,created_at=now,old_assigned_staff_user_id=b.assigned_staff_user_id,
        new_assigned_staff_user_id=b.assigned_staff_user_id,details={"boarding_note_id":str(nid)}))
    db.flush()
    n=BoardingNote(id=nid,stay_id=s.id,event_id=eid,actor_user_id=user.id,note=payload.note,created_at=now)
    db.add(n);db.commit()
    return note_view(n)
