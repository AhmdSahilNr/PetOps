"""Remaining frozen MUST management/review, bounded to approved roles/actions."""
from datetime import date,datetime,time,timedelta,timezone
from uuid import UUID
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy import delete,select,func,or_,case
from typing import Literal

from .database import get_db
from .models import (Booking,BookingStatus,Customer,ManagementEvent,NotificationSetting,
    Pet,Role,Service,ServiceType,User,UserSession,utcnow)
from .schemas import (InputModel,ReminderSettingIn,RescheduleIn,ServiceCreateIn,
    ServiceUpdateIn,StaffCreateIn,StaffUpdateIn)
from .security import hash_password,normalize_email,require_roles
from .services import cancel_booking,reschedule_booking,utc_iso
from .views import booking_view

router=APIRouter(prefix='/admin',tags=['Admin management/review'])
admin=require_roles(Role.ADMIN)
BUSINESS_ZONE=ZoneInfo('Asia/Kuala_Lumpur')


def period_bounds(start,end):
    if end<start or end==date.max or start==date.min:raise HTTPException(422,'Choose an ordered reporting period within supported dates')
    return (datetime.combine(start,time.min,BUSINESS_ZONE).astimezone(timezone.utc),
        datetime.combine(end+timedelta(days=1),time.min,BUSINESS_ZONE).astimezone(timezone.utc))


def staff_view(u):return {'id':str(u.id),'email':u.email,'display_name':u.display_name,'is_active':u.is_active,'created_at':utc_iso(u.created_at)}
def service_view(s):return {'id':str(s.id),'name':s.name,'service_type':s.service_type.value,'is_active':s.is_active,
    'duration_minutes':s.duration_minutes,'display_order':s.display_order,'updated_by_user_id':str(s.updated_by_user_id) if s.updated_by_user_id else None,'updated_at':utc_iso(s.updated_at)}
def setting_view(s):return {'enabled':s.enabled,'lead_minutes':s.lead_minutes,
    'boarding_reference':'00:00 Asia/Kuala_Lumpur on reserved start date (reminder reference only)',
    'updated_by_user_id':str(s.updated_by_user_id) if s.updated_by_user_id else None,'updated_at':utc_iso(s.updated_at)}


def audit(db,user,action,details,**target):
    db.add(ManagementEvent(actor_user_id=user.id,action=action,details=details,**target))


@router.get('/staff')
def staff_list(user=Depends(admin),db=Depends(get_db)):
    return [staff_view(u) for u in db.scalars(select(User).where(User.role==Role.STAFF).order_by(User.email))]


@router.post('/staff',status_code=201)
def create_staff(payload:StaffCreateIn,user=Depends(admin),db=Depends(get_db)):
    u=User(email=normalize_email(str(payload.email)),password_hash=hash_password(payload.password),role=Role.STAFF,is_active=payload.is_active,display_name=payload.display_name)
    db.add(u);db.flush();audit(db,user,'STAFF_CREATED',{'new':staff_view(u)},staff_user_id=u.id)
    db.commit();return staff_view(u)


@router.put('/staff/{staff_id}')
def update_staff(staff_id:UUID,payload:StaffUpdateIn,user=Depends(admin),db=Depends(get_db)):
    u=db.scalar(select(User).where(User.id==staff_id,User.role==Role.STAFF).with_for_update())
    if not u:raise HTTPException(404,'Staff account not found')
    if not payload.is_active:
        from .models import StaffResponsibility
        from sqlalchemy import func
        if db.scalar(select(StaffResponsibility.id).join(Booking,Booking.id==StaffResponsibility.booking_id).where(StaffResponsibility.staff_user_id==u.id,StaffResponsibility.released_at.is_(None),
            (func.coalesce(StaffResponsibility.ended_at,StaffResponsibility.ends_at)>utcnow())|((StaffResponsibility.ended_at.is_(None))&(StaffResponsibility.starts_at<=utcnow())&Booking.status.in_([BookingStatus.IN_PROGRESS,BookingStatus.STAYING,BookingStatus.CHECKED_IN]))).limit(1)):
            raise HTTPException(409,'Reassign or finish current/upcoming work before deactivating this Staff member')
    old=staff_view(u)
    if 'display_name' in payload.model_fields_set:u.display_name=payload.display_name
    u.email=normalize_email(str(payload.email));u.is_active=payload.is_active
    if payload.password is not None:u.password_hash=hash_password(payload.password)
    if not u.is_active or payload.password is not None:
        db.execute(delete(UserSession).where(UserSession.user_id==u.id))
    db.flush();audit(db,user,'STAFF_UPDATED',{'old':old,'new':staff_view(u),'password_changed':payload.password is not None},staff_user_id=u.id)
    db.commit();return staff_view(u)


@router.get('/services')
def service_list(user=Depends(admin),db=Depends(get_db)):
    return [service_view(s) for s in db.scalars(select(Service).order_by(Service.service_type,Service.display_order,Service.name,Service.id))]


@router.post('/services',status_code=201)
def create_service(payload:ServiceCreateIn,user=Depends(admin),db=Depends(get_db)):
    s=Service(**payload.model_dump(),updated_by_user_id=user.id,updated_at=utcnow())
    db.add(s);db.flush();audit(db,user,'SERVICE_CREATED',{'new':service_view(s)},service_id=s.id)
    db.commit();return service_view(s)


@router.put('/services/{service_id}')
def update_service(service_id:UUID,payload:ServiceUpdateIn,user=Depends(admin),db=Depends(get_db)):
    s=db.scalar(select(Service).where(Service.id==service_id).with_for_update())
    if not s:raise HTTPException(404,'Service not found')
    duration=payload.duration_minutes if 'duration_minutes' in payload.model_fields_set else s.duration_minutes
    if (s.service_type==ServiceType.GROOMING and payload.is_active and duration is None) or (s.service_type==ServiceType.BOARDING and duration is not None):
        raise HTTPException(422,'Active Grooming requires duration; Boarding must not have duration')
    old=service_view(s)
    if payload.display_order is not None:s.display_order=payload.display_order
    s.name,s.is_active,s.duration_minutes=payload.name,payload.is_active,duration
    s.updated_by_user_id,s.updated_at=user.id,utcnow();db.flush()
    audit(db,user,'SERVICE_UPDATED',{'old':old,'new':service_view(s)},service_id=s.id)
    db.commit();return service_view(s)


@router.get('/notification-settings')
def get_settings(user=Depends(admin),db=Depends(get_db)):
    return setting_view(db.get(NotificationSetting,1))


@router.put('/notification-settings')
def update_settings(payload:ReminderSettingIn,user=Depends(admin),db=Depends(get_db)):
    s=db.scalar(select(NotificationSetting).where(NotificationSetting.id==1).with_for_update());old=setting_view(s)
    s.enabled,s.lead_minutes=payload.enabled,payload.lead_minutes;s.updated_by_user_id,s.updated_at=user.id,utcnow()
    db.flush();audit(db,user,'REMINDER_SETTINGS_UPDATED',{'old':old,'new':setting_view(s)},notification_setting_id=1)
    db.commit();return setting_view(s)


@router.get('/customers')
def customer_choices(user=Depends(admin),db=Depends(get_db)):
    return [{'id':str(c.id),'display_name':c.display_name,'email':u.email} for c,u in db.execute(select(Customer,User).join(User,User.id==Customer.user_id).order_by(Customer.display_name))]


@router.get('/customers/{customer_id}/pets')
def customer_pet_choices(customer_id:UUID,user=Depends(admin),db=Depends(get_db)):
    if not db.get(Customer,customer_id):raise HTTPException(404,'Customer not found')
    return [{'id':str(p.id),'name':p.name} for p in db.scalars(select(Pet).where(Pet.customer_id==customer_id).order_by(Pet.name))]


@router.get('/history')
def filtered_history(user=Depends(admin),db=Depends(get_db),customer_id:UUID|None=None,pet_id:UUID|None=None,
    service_type:ServiceType|None=None,status:BookingStatus|None=None,from_date:date|None=None,to_date:date|None=None,
    search:str=Query('',max_length=120,pattern=r'^[^\x00]*$'),date_basis:Literal['created','service']='created',sort:Literal['newest','oldest','service']='newest',
    limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0)):
    q=select(Booking)
    service_date=case((Booking.booking_type==ServiceType.GROOMING,func.timezone('Asia/Kuala_Lumpur',Booking.grooming_start).cast(__import__('sqlalchemy').Date)),else_=Booking.boarding_start)
    if search.strip():
        term='%'+search.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        q=q.join(Customer,Customer.id==Booking.customer_id).join(Pet,Pet.id==Booking.pet_id).where(or_(Customer.display_name.ilike(term,escape='\\'),Pet.name.ilike(term,escape='\\')))
    if customer_id:
        if not db.get(Customer,customer_id):raise HTTPException(404,'Customer not found')
        q=q.where(Booking.customer_id==customer_id)
    if pet_id:
        p=db.get(Pet,pet_id)
        if not p or (customer_id and p.customer_id!=customer_id):raise HTTPException(404,'Pet not found for selected Customer')
        q=q.where(Booking.pet_id==pet_id)
    if service_type:q=q.where(Booking.booking_type==service_type)
    if status:q=q.where(Booking.status.in_([BookingStatus.STAYING,BookingStatus.CHECKED_IN]) if status==BookingStatus.STAYING else Booking.status.in_([BookingStatus.COMPLETED,BookingStatus.CHECKED_OUT]) if status==BookingStatus.COMPLETED else Booking.status==status)
    if (from_date is None)!=(to_date is None):raise HTTPException(422,'Provide both period dates')
    if from_date:
        lo,hi=period_bounds(from_date,to_date)
        q=q.where(service_date>=from_date,service_date<=to_date) if date_basis=='service' else q.where(Booking.created_at>=lo,Booking.created_at<hi)
    total=db.scalar(select(func.count()).select_from(q.subquery()))
    ordering={'newest':Booking.created_at.desc(),'oldest':Booking.created_at.asc(),'service':service_date.asc()}[sort]
    rows=db.scalars(q.order_by(ordering,Booking.id).offset(offset).limit(limit)).all()
    return {'items':[{**booking_view(b),'customer_name':db.get(Customer,b.customer_id).display_name,
        'pet_name':db.get(Pet,b.pet_id).name,'service_name':db.get(Service,b.service_id).name} for b in rows],
        'limit':limit,'offset':offset,'total':total,'date_basis':date_basis,'period_basis':'Service start date (MYT)' if date_basis=='service' else 'Booking created date (MYT)'}


@router.get('/bookings/{booking_id}/history')
def operational_history(booking_id:UUID,user=Depends(admin),db=Depends(get_db)):
    b=db.get(Booking,booking_id)
    if not b:raise HTTPException(404,'Booking not found')
    if b.booking_type==ServiceType.GROOMING:
        from .grooming_routes import detail
    else:
        from .boarding_routes import detail
    return detail(db,b)


def locked_booking(db,booking_id):
    b=db.scalar(select(Booking).where(Booking.id==booking_id).with_for_update())
    if not b:raise HTTPException(404,'Booking not found')
    return b


@router.post('/bookings/{booking_id}/reschedule')
def admin_reschedule(booking_id:UUID,payload:RescheduleIn,user=Depends(admin),db=Depends(get_db)):
    return booking_view(reschedule_booking(db,locked_booking(db,booking_id),user,**payload.model_dump()))


@router.post('/bookings/{booking_id}/cancel')
def admin_cancel(booking_id:UUID,payload:InputModel,user=Depends(admin),db=Depends(get_db)):
    return booking_view(cancel_booking(db,locked_booking(db,booking_id),user))


@router.get('/management-history')
def management_history(user=Depends(admin),db=Depends(get_db),limit:int=Query(100,ge=1,le=200)):
    return [{'id':str(e.id),'action':e.action,'actor_user_id':str(e.actor_user_id),'actor_name':db.get(User,e.actor_user_id).display_name or 'Admin','actor_email':db.get(User,e.actor_user_id).email,'created_at':utc_iso(e.created_at),
        'staff_user_id':str(e.staff_user_id) if e.staff_user_id else None,'service_id':str(e.service_id) if e.service_id else None,
        'notification_setting_id':e.notification_setting_id,'details':e.details}
        for e in db.scalars(select(ManagementEvent).order_by(ManagementEvent.created_at.desc(),ManagementEvent.id).limit(limit))]

@router.get('/assignments')
def assignment_register(user=Depends(admin),db=Depends(get_db)):
    from .models import StaffResponsibility
    from .responsibilities import view
    return [{**view(db,row),'booking':booking_view(db.get(Booking,row.booking_id)),
        'pet_name':db.get(Pet,db.get(Booking,row.booking_id).pet_id).name} for row in db.scalars(select(StaffResponsibility).order_by(StaffResponsibility.starts_at.desc(),StaffResponsibility.id))]
