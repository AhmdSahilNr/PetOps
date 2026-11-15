"""Approved operational measures with explicit date bases; no financial KPIs."""
from datetime import date,timedelta
from fastapi import APIRouter,Depends
from sqlalchemy import func,select,text
from sqlalchemy.orm import Session

from .availability import ACTIVE_WORK
from .database import get_engine
from .management import period_bounds
from .models import (Accommodation,BoardingAllocation,BoardingStay,Booking,BookingEvent,
    BookingStatus,GroomingRecord,Role,ServiceType,StaffResponsibility,User,utcnow)
from .security import require_roles
from .services import business_today,utc_iso
from .views import booking_view

router=APIRouter(prefix='/admin',tags=['Admin operational dashboard'])


def insight_measures(db,start,end,lo,hi,now):
    """Read existing facts only; decision events are not unique bookings."""
    decisions={BookingStatus.CONFIRMED:0,BookingStatus.REJECTED:0}
    for status,count in db.execute(select(BookingEvent.new_status,func.count()).where(
        BookingEvent.event_type=='STATUS_CHANGED',BookingEvent.new_status.in_(decisions),
        BookingEvent.created_at>=lo,BookingEvent.created_at<hi).group_by(BookingEvent.new_status)):
        decisions[status]=count
    confirmed,rejected=decisions[BookingStatus.CONFIRMED],decisions[BookingStatus.REJECTED]
    denominator=confirmed+rejected
    bucket_size='week' if (end-start).days<93 else 'month'
    bucket=func.date_trunc(bucket_size,func.timezone('Asia/Kuala_Lumpur',Booking.created_at))
    buckets={}
    for period,kind,count in db.execute(select(bucket,Booking.booking_type,func.count()).where(
        Booking.created_at>=lo,Booking.created_at<hi).group_by(bucket,Booking.booking_type).order_by(bucket)):
        key=period.date().isoformat()
        row=buckets.setdefault(key,{'period_start':key,'GROOMING':0,'BOARDING':0,'total':0})
        row[kind.value]=count;row['total']+=count
    today=business_today();last=today+timedelta(days=6)
    _,near_end=period_bounds(today,last)
    near={'from_date':today.isoformat(),'to_date':last.isoformat(),
        'grooming_appointments':db.scalar(select(func.count()).select_from(Booking).where(
            Booking.booking_type==ServiceType.GROOMING,Booking.status==BookingStatus.CONFIRMED,
            Booking.grooming_start>=now,Booking.grooming_start<near_end)),
        'boarding_arrivals':db.scalar(select(func.count()).select_from(Booking).where(
            Booking.booking_type==ServiceType.BOARDING,Booking.status==BookingStatus.CONFIRMED,
            Booking.boarding_start>=today,Booking.boarding_start<=last)),
        'boarding_departures':db.scalar(select(func.count()).select_from(Booking).where(
            Booking.booking_type==ServiceType.BOARDING,
            Booking.status.in_([BookingStatus.CONFIRMED,BookingStatus.CHECKED_IN,BookingStatus.STAYING]),
            Booking.boarding_end>=today,Booking.boarding_end<=last)),
        'active_boarding_stays':db.scalar(select(func.count()).select_from(BoardingStay).where(BoardingStay.checked_out_at.is_(None))),
        'requests_needing_review':db.scalar(select(func.count()).select_from(Booking).where(Booking.status==BookingStatus.SUBMITTED))}
    return {'confirmation_decisions':{'confirmed':confirmed,'rejected':rejected,'decided':denominator,
            'confirmation_rate_percent':round(confirmed*100/denominator,2) if denominator else None},
        'booking_volume':{'bucket_size':bucket_size,'buckets':list(buckets.values()),'zero_buckets_omitted':True},
        'next_seven_days':near}


def report(db,start,end):
    lo,hi=period_bounds(start,end);now=utcnow()
    cohort=(Booking.created_at>=lo,Booking.created_at<hi)
    statuses={s.value:0 for s in BookingStatus};types={t.value:0 for t in ServiceType}
    for status,count in db.execute(select(Booking.status,func.count()).where(*cohort).group_by(Booking.status)):statuses[status.value]=count
    for kind,count in db.execute(select(Booking.booking_type,func.count()).where(*cohort).group_by(Booking.booking_type)):types[kind.value]=count
    completed={}
    for kind,model in [('GROOMING',GroomingRecord),('BOARDING',BoardingStay)]:
        completed[kind]=db.scalar(select(func.count()).select_from(model).where(model.completed_at>=lo,model.completed_at<hi))
    changes={kind:db.scalar(select(func.count()).select_from(BookingEvent).where(BookingEvent.event_type==kind,
        BookingEvent.created_at>=lo,BookingEvent.created_at<hi)) for kind in ('BOOKING_CANCELLED','BOOKING_RESCHEDULED')}
    workload=[]
    for staff in db.scalars(select(User).where(User.role==Role.STAFF).order_by(User.email)):
        base=(Booking.assigned_staff_user_id==staff.id,Booking.status.in_(ACTIVE_WORK))
        scheduled=db.scalar(select(func.count(func.distinct(StaffResponsibility.booking_id))).select_from(StaffResponsibility).join(Booking,Booking.id==StaffResponsibility.booking_id).where(StaffResponsibility.staff_user_id==staff.id,StaffResponsibility.released_at.is_(None),Booking.status.in_(ACTIVE_WORK),StaffResponsibility.starts_at<hi,func.coalesce(StaffResponsibility.ended_at,StaffResponsibility.ends_at)>lo))
        unknown=db.scalar(select(func.count()).select_from(Booking).where(*base,(Booking.staff_start.is_(None)|Booking.staff_end.is_(None))))
        workload.append({'staff_user_id':str(staff.id),'email':staff.email,'display_name':staff.display_name,'is_active':staff.is_active,
            'active_assigned_bookings_in_period':scheduled,'active_assignments_without_recorded_period':unknown})
    units=[]
    for unit in db.scalars(select(Accommodation).order_by(Accommodation.name)):
        occupied=db.scalar(select(func.count()).select_from(BoardingStay).join(BoardingAllocation,BoardingAllocation.id==BoardingStay.allocation_id)
            .where(BoardingAllocation.accommodation_id==unit.id,BoardingStay.checked_out_at.is_(None)))
        units.append({'id':str(unit.id),'name':unit.name,'is_active':unit.is_active,'configured_capacity':unit.capacity,
            'physically_occupied':occupied,'available_places':max(0,unit.capacity-occupied) if unit.is_active else 0,
            'utilisation_percent':round(occupied*100/unit.capacity,2) if unit.is_active else None})
    capacity=sum(u['configured_capacity'] for u in units if u['is_active']);occupied=sum(u['physically_occupied'] for u in units)
    today=business_today()
    common=(Booking.booking_type==ServiceType.BOARDING,)
    arrivals_q=select(Booking).where(*common,Booking.status==BookingStatus.CONFIRMED,
        Booking.boarding_start>=today,Booking.boarding_start>=start,Booking.boarding_start<=end)
    departures_q=select(Booking).where(*common,Booking.status.in_([BookingStatus.CONFIRMED,BookingStatus.CHECKED_IN,BookingStatus.STAYING]),
        Booking.boarding_end>=today,Booking.boarding_end>=start,Booking.boarding_end<=end)
    arrivals=db.scalars(arrivals_q.order_by(Booking.boarding_start,Booking.id).limit(200)).all()
    departures=db.scalars(departures_q.order_by(Booking.boarding_end,Booking.id).limit(200)).all()
    return {**insight_measures(db,start,end,lo,hi,now),
        'period':{'from_date':start.isoformat(),'to_date':end.isoformat(),'timezone':'Asia/Kuala_Lumpur','utc_start':utc_iso(lo),'utc_end_exclusive':utc_iso(hi)},
        'total_bookings':sum(statuses.values()),'bookings_by_status':statuses,'bookings_by_type':types,
        'completed_services_by_type':completed,'booking_change_events':changes,'staff_workload':workload,
        'boarding_current':{'as_of':utc_iso(now),'configured_active_capacity':capacity,'physically_occupied':occupied,
            'available_places':sum(u['available_places'] for u in units),'utilisation_percent':round(occupied*100/capacity,2) if capacity else None,'units':units},
        'upcoming_arrivals':{'total':db.scalar(select(func.count()).select_from(arrivals_q.subquery())),'items':[booking_view(b) for b in arrivals],'limit':200},
        'upcoming_departures':{'total':db.scalar(select(func.count()).select_from(departures_q.subquery())),'items':[booking_view(b) for b in departures],'limit':200},
        'definitions':{'bookings':'Created in selected period; status/type are their current values.',
            'completed_services':'Actual Grooming/Boarding completion timestamp in selected period.',
            'changes':'Recorded cancellation/reschedule events in selected period; not unique bookings.',
            'workload':'Current unreleased responsibilities overlapping selected period; distinct bookings, not hours or productivity. Legacy missing periods are separate.',
            'boarding_current':'Current physical occupancy and current configured active capacity; independent of selected period and includes overdue open stays.',
            'arrivals_departures':'Upcoming planned stay dates inside selected inclusive dates; cancelled/rejected/completed work excluded.',
            'confirmation_decisions':'Confirmed STATUS_CHANGED decisions / confirmed plus rejected STATUS_CHANGED decisions at event time in selected period; reconfirmation counts as another decision, later cancellation does not erase it. No decisions gives null.',
            'booking_volume':'Bookings created in selected MYT period, grouped by MYT Monday weeks for up to93 inclusive days, otherwise calendar months. Only non-empty buckets shown.',
            'next_seven_days':'Independent of reporting period: from now to the end of the sixth following MYT date. Confirmed future Grooming, planned confirmed arrivals, confirmed/open departures; open physical stays and pending review are current snapshots.',
            'omissions':'No revenue, profitability, cancellation-reason analysis or invented historical capacity utilisation.'}}


@router.get('/dashboard')
def dashboard(from_date:date,to_date:date,user=Depends(require_roles(Role.ADMIN))):
    period_bounds(from_date,to_date)
    # Auth uses its own session; every metric below shares one read-only snapshot.
    with get_engine().connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        with Session(connection) as db:
            db.execute(text('SET TRANSACTION READ ONLY'))
            return report(db,from_date,to_date)
