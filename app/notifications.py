"""Approved in-system notices and one idempotent reminder generator."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
import logging
import os
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import exists, func, select, text
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool

from .database import SessionLocal, get_db
from .models import (Booking, BookingEvent, BookingStatus, Customer, Notification,
    NotificationSetting, Role, User, utcnow)
from .security import require_roles
from .schemas import InputModel
from .services import utc_iso

router=APIRouter(tags=["In-system notifications"])
recipients=require_roles(Role.CUSTOMER,Role.STAFF)
MESSAGES={
    "BOOKING_SUBMITTED":"Your booking request was received.",
    "BOOKING_CONFIRMED":"Your booking was confirmed.",
    "BOOKING_REJECTED":"Your booking request was rejected.",
    "BOOKING_RESCHEDULED":"Your changed request was received and requires Admin review.",
    "BOOKING_RECONFIRMED":"Your changed booking was confirmed again.",
    "RESCHEDULE_REJECTED":"Your changed booking request was rejected.",
    "BOOKING_CANCELLED":"Your booking was cancelled.",
    "STAFF_ASSIGNED":"You have been assigned this service.",
    "STAFF_REASSIGNED":"Your responsibility for this service has changed.",
    "BOOKING_REMINDER":"Reminder: your confirmed booking is approaching.",
}


def notification_view(db,n):
    from .responsibilities import can_inspect
    from .models import Pet,Service
    from .services import schedule_snapshot
    b=db.get(Booking,n.booking_id)
    permitted=(db.get(Customer,b.customer_id).user_id==n.recipient_user_id) if n.recipient_role==Role.CUSTOMER else can_inspect(db,b,n.recipient_user_id)
    event=db.get(BookingEvent,n.source_event_id)
    context=(event.details or {}).get('notice_context',{}) if event else {}
    # Legacy notices have no event snapshot. Only an entitled account may resolve current names.
    if not context and permitted:
        context={'pet_name':db.get(Pet,b.pet_id).name,'service_name':db.get(Service,b.service_id).name,'schedule':event.new_schedule if event and event.new_schedule else schedule_snapshot(b)}
    category='Grooming' if b.booking_type.value=='GROOMING' else 'Boarding'
    staff=n.recipient_role==Role.STAFF
    label={'BOOKING_SUBMITTED':'request received','BOOKING_CONFIRMED':'booking confirmed','BOOKING_RECONFIRMED':'booking confirmed again',
        'BOOKING_REJECTED':'request rejected','RESCHEDULE_REJECTED':'changed request rejected','BOOKING_RESCHEDULED':'dates changed',
        'BOOKING_CANCELLED':'booking cancelled','BOOKING_REMINDER':'booking reminder','STAFF_ASSIGNED':'assigned','STAFF_REASSIGNED':'assignment changed'}.get(n.kind,'booking update')
    message=MESSAGES[n.kind]
    if staff:
        if not permitted:message='You are no longer responsible for this service.'
        elif n.kind in {'STAFF_ASSIGNED','STAFF_REASSIGNED'}:message='You have been assigned this Grooming appointment.' if category=='Grooming' else 'You are responsible for this Boarding stay during your recorded assignment period.'
    elif n.kind=='BOOKING_CONFIRMED':message=f'Your {category} request has been confirmed.'
    return {"id":str(n.id),"kind":n.kind,"message":message,'title':f'{category} {label}'+(' — '+context['pet_name'] if context.get('pet_name') else ''),
        'pet_name':context.get('pet_name'),'service_name':context.get('service_name'),'schedule':context.get('schedule'),
        'can_view_booking':permitted,'cta_label':('View assignment' if staff else 'View booking') if permitted else None,
        "booking_id":str(n.booking_id),"booking_type":b.booking_type.value,
        "created_at":utc_iso(n.created_at),"read_at":utc_iso(n.read_at),
        "schedule_reference":utc_iso(n.schedule_reference),"lead_minutes":n.lead_minutes}


def generate_due_reminders(db):
    if db.bind.dialect.name!='postgresql':
        raise RuntimeError("Reminder generation requires the verified PostgreSQL implementation")
    db.execute(text("SET LOCAL lock_timeout='2s'"));db.execute(text("SET LOCAL statement_timeout='5s'"))
    cfg=db.scalar(select(NotificationSetting).where(NotificationSetting.id==1).with_for_update(read=True))
    if not cfg or not cfg.enabled or cfg.lead_minutes is None:return 0
    now=utcnow()
    latest=(select(BookingEvent.id).where(BookingEvent.booking_id==Booking.id,
        BookingEvent.event_type=='STATUS_CHANGED',BookingEvent.new_status==BookingStatus.CONFIRMED)
        .order_by(BookingEvent.created_at.desc(),BookingEvent.id.desc()).limit(1).correlate(Booking).scalar_subquery())
    reference=func.petops_reminder_reference(Booking.id)
    already=exists(select(Notification.id).where(Notification.booking_id==Booking.id,
        Notification.source_event_id==latest,Notification.kind=='BOOKING_REMINDER'))
    rows=db.scalars(select(Booking).join(Customer,Customer.id==Booking.customer_id)
        .join(User,User.id==Customer.user_id).where(Booking.status==BookingStatus.CONFIRMED,
            User.is_active.is_(True),latest.is_not(None),reference>now,
            reference<=now+timedelta(minutes=cfg.lead_minutes),~already)
        .order_by(Booking.id).limit(200).with_for_update(of=Booking,skip_locked=True)).all()
    created=0
    for b in rows:
        event=db.scalar(select(BookingEvent).where(BookingEvent.booking_id==b.id,
            BookingEvent.event_type=='STATUS_CHANGED',BookingEvent.new_status==BookingStatus.CONFIRMED)
            .order_by(BookingEvent.created_at.desc(),BookingEvent.id.desc()).limit(1))
        owner=db.get(Customer,b.customer_id)
        ref=db.scalar(select(func.petops_reminder_reference(b.id)))
        if ref<=utcnow():continue
        stmt=insert(Notification).values(id=uuid4(),recipient_user_id=owner.user_id,recipient_role=Role.CUSTOMER,
            booking_id=b.id,source_event_id=event.id,kind='BOOKING_REMINDER',created_at=utcnow(),
            schedule_reference=ref,lead_minutes=cfg.lead_minutes).on_conflict_do_nothing(
                constraint='uq_notification_event_recipient_kind').returning(Notification.id)
        created+=int(db.scalar(stmt) is not None)
    return created


def reminder_job():
    with SessionLocal() as db:
        count=generate_due_reminders(db);db.commit();return count


@asynccontextmanager
async def lifespan(app):
    try:interval=float(os.getenv('PETOPS_REMINDER_POLL_SECONDS','60'))
    except ValueError:raise RuntimeError('PETOPS_REMINDER_POLL_SECONDS must be numeric')
    if interval<0:raise RuntimeError('Reminder poll interval cannot be negative')
    stopped=asyncio.Event()
    async def poll():
        while not stopped.is_set():
            try:await asyncio.wait_for(stopped.wait(),timeout=interval)
            except asyncio.TimeoutError:
                try:await run_in_threadpool(reminder_job)
                except Exception as exc:
                    # Never log URLs, SQL parameters, session data or exception text.
                    logging.getLogger('petops.reminders').warning('Reminder sweep unavailable (%s)',type(exc).__name__)
    task=asyncio.create_task(poll()) if interval>0 else None
    try:yield
    finally:
        stopped.set()
        if task:
            with suppress(asyncio.CancelledError):await task


@router.get('/notifications')
def inbox(user=Depends(recipients),db=Depends(get_db),limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0)):
    rows=db.scalars(select(Notification).where(Notification.recipient_user_id==user.id)
        .order_by(Notification.created_at.desc(),Notification.id.desc()).offset(offset).limit(limit)).all()
    unread=db.scalar(select(func.count()).select_from(Notification).where(Notification.recipient_user_id==user.id,Notification.read_at.is_(None)))
    return {'items':[notification_view(db,n) for n in rows],'unread_count':unread,'limit':limit,'offset':offset}


@router.get('/notifications/{notification_id}')
def own_notification(notification_id:UUID,user=Depends(recipients),db=Depends(get_db)):
    n=db.scalar(select(Notification).where(Notification.id==notification_id,Notification.recipient_user_id==user.id))
    if not n:raise HTTPException(404,'Notification not found')
    return notification_view(db,n)


@router.post('/notifications/{notification_id}/read')
def read_notification(notification_id:UUID,payload:InputModel,user=Depends(recipients),db=Depends(get_db)):
    n=db.scalar(select(Notification).where(Notification.id==notification_id,Notification.recipient_user_id==user.id).with_for_update())
    if not n:raise HTTPException(404,'Notification not found')
    if n.read_at is None:n.read_at=utcnow();db.commit()
    return notification_view(db,n)


@router.post('/admin/reminders/run')
def run_due_reminders(payload:InputModel,user=Depends(require_roles(Role.ADMIN)),db=Depends(get_db)):
    count=generate_due_reminders(db);db.commit();return {'created':count}
