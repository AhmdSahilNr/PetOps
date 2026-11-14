-- C00B approved merged arrival/departure; existing histories remain unchanged.
CREATE OR REPLACE FUNCTION petops_guard_boarding_booking() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.booking_type='BOARDING' AND NEW.status IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED') THEN
     RAISE EXCEPTION 'Boarding work must progress from confirmation' USING ERRCODE='23514';
   END IF;
   RETURN NEW;
 END IF;
 IF NEW.booking_type='BOARDING' AND NEW.status IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED') AND OLD.booking_type<>'BOARDING' THEN
   RAISE EXCEPTION 'Cannot convert another workflow into operational Boarding' USING ERRCODE='23514';
 END IF;
 IF OLD.booking_type='BOARDING' AND (OLD.status IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED')
     OR NEW.status IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED')) THEN
   IF (NEW.customer_id,NEW.pet_id,NEW.service_id,NEW.booking_type,NEW.boarding_start,NEW.boarding_end,
       NEW.assigned_staff_user_id,NEW.staff_start,NEW.staff_end,NEW.created_by_user_id,NEW.created_at)
      IS DISTINCT FROM
      (OLD.customer_id,OLD.pet_id,OLD.service_id,OLD.booking_type,OLD.boarding_start,OLD.boarding_end,
       OLD.assigned_staff_user_id,OLD.staff_start,OLD.staff_end,OLD.created_by_user_id,OLD.created_at) THEN
     RAISE EXCEPTION 'Operational Boarding links, dates and assignment are retained' USING ERRCODE='23514';
   END IF;
   IF NEW.status<>OLD.status AND NOT
      ((OLD.status='CONFIRMED' AND NEW.status='STAYING') OR
       (OLD.status='STAYING' AND NEW.status='COMPLETED') OR
       (EXISTS (SELECT 1 FROM public.booking_events e WHERE e.booking_id=OLD.id AND e.event_type='BOARDING_CHECKED_IN' AND e.new_status='CHECKED_IN') AND (
       (OLD.status='CONFIRMED' AND NEW.status='CHECKED_IN') OR
       (OLD.status='CHECKED_IN' AND NEW.status='STAYING') OR
       (OLD.status='STAYING' AND NEW.status='CHECKED_OUT') OR
       (OLD.status='CHECKED_OUT' AND NEW.status='COMPLETED')))) THEN
     RAISE EXCEPTION 'Invalid Boarding operational transition' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION petops_guard_boarding_stay() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; a public.boarding_allocations%ROWTYPE; actor uuid; acted timestamptz;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Boarding history cannot be deleted' USING ERRCODE='23514'; END IF;
 SELECT * INTO b FROM public.bookings WHERE id=NEW.booking_id FOR UPDATE;
 IF NOT FOUND OR b.booking_type<>'BOARDING' THEN
   RAISE EXCEPTION 'Stay requires a Boarding booking' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
   SELECT * INTO a FROM public.boarding_allocations WHERE id=NEW.allocation_id;
   IF NOT FOUND OR b.status<>'STAYING' OR a.booking_id<>b.id OR a.released_at IS NOT NULL
      OR a.starts_on<>b.boarding_start OR a.ends_on<>b.boarding_end
      OR NEW.stay_started_at IS DISTINCT FROM NEW.checked_in_at
      OR NEW.stay_started_by_user_id IS DISTINCT FROM NEW.checked_in_by_user_id OR NEW.checked_out_at IS NOT NULL OR NEW.completed_at IS NOT NULL
      OR (clock_timestamp() AT TIME ZONE 'Asia/Kuala_Lumpur')::date < b.boarding_start
      OR (clock_timestamp() AT TIME ZONE 'Asia/Kuala_Lumpur')::date >= b.boarding_end
      OR NEW.checked_in_at<b.created_at THEN
     RAISE EXCEPTION 'Check-in requires confirmed matching accommodation within reserved dates' USING ERRCODE='23514';
   END IF;
   actor:=NEW.checked_in_by_user_id; acted:=NEW.checked_in_at;
 ELSE
   IF (NEW.id,NEW.booking_id,NEW.allocation_id,NEW.checked_in_by_user_id,NEW.checked_in_at)
      IS DISTINCT FROM (OLD.id,OLD.booking_id,OLD.allocation_id,OLD.checked_in_by_user_id,OLD.checked_in_at)
      OR OLD.completed_at IS NOT NULL THEN
     RAISE EXCEPTION 'Stay identity and prior attribution are immutable' USING ERRCODE='23514';
   END IF;
   IF OLD.stay_started_at IS NULL AND NEW.stay_started_at IS NOT NULL
      AND NEW.checked_out_at IS NULL AND NEW.completed_at IS NULL AND b.status='STAYING' THEN
     actor:=NEW.stay_started_by_user_id; acted:=NEW.stay_started_at;
   ELSIF OLD.stay_started_at IS NOT NULL AND OLD.checked_out_at IS NULL
      AND NEW.checked_out_at IS NOT NULL AND NEW.completed_at=NEW.checked_out_at
      AND NEW.completed_by_user_id=NEW.checked_out_by_user_id AND b.status='COMPLETED'
      AND (NEW.stay_started_by_user_id,NEW.stay_started_at) IS NOT DISTINCT FROM (OLD.stay_started_by_user_id,OLD.stay_started_at) THEN
     actor:=NEW.checked_out_by_user_id; acted:=NEW.checked_out_at;
   ELSIF OLD.stay_started_at IS NOT NULL AND OLD.checked_out_at IS NULL AND NEW.checked_out_at IS NOT NULL
      AND NEW.completed_at IS NULL AND b.status='CHECKED_OUT'
      AND (NEW.stay_started_by_user_id,NEW.stay_started_at) IS NOT DISTINCT FROM (OLD.stay_started_by_user_id,OLD.stay_started_at) THEN
     actor:=NEW.checked_out_by_user_id; acted:=NEW.checked_out_at;
   ELSIF OLD.checked_out_at IS NOT NULL AND NEW.completed_at IS NOT NULL AND b.status='COMPLETED'
      AND (NEW.stay_started_by_user_id,NEW.stay_started_at,NEW.checked_out_by_user_id,NEW.checked_out_at)
       IS NOT DISTINCT FROM (OLD.stay_started_by_user_id,OLD.stay_started_at,OLD.checked_out_by_user_id,OLD.checked_out_at) THEN
     actor:=NEW.completed_by_user_id; acted:=NEW.completed_at;
   ELSE RAISE EXCEPTION 'Only a single forward stay step is allowed' USING ERRCODE='23514';
   END IF;
 END IF;
 IF acted IS NULL OR acted>clock_timestamp() THEN
   RAISE EXCEPTION 'Actual operational timestamp required' USING ERRCODE='23514';
 END IF;
 PERFORM public.petops_require_boarding_actor(actor,b.assigned_staff_user_id);
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION petops_validate_boarding(which uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; s public.boarding_stays%ROWTYPE; a public.boarding_allocations%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.bookings WHERE id=which;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT * INTO s FROM public.boarding_stays WHERE booking_id=which;
 IF NOT FOUND THEN
   IF (b.booking_type='BOARDING' AND b.status IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED'))
      OR EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type LIKE 'BOARDING_%') THEN
     RAISE EXCEPTION 'Boarding operational record required' USING ERRCODE='23514';
   END IF;
   RETURN;
 END IF;
 IF b.booking_type<>'BOARDING' OR b.status NOT IN ('CHECKED_IN','STAYING','CHECKED_OUT','COMPLETED')
    OR (b.status='CHECKED_IN' AND (s.stay_started_at IS NOT NULL OR s.checked_out_at IS NOT NULL OR s.completed_at IS NOT NULL))
    OR (b.status='STAYING' AND (s.stay_started_at IS NULL OR s.checked_out_at IS NOT NULL OR s.completed_at IS NOT NULL))
    OR (b.status='CHECKED_OUT' AND (s.checked_out_at IS NULL OR s.completed_at IS NOT NULL))
    OR (b.status='COMPLETED' AND s.completed_at IS NULL) THEN
   RAISE EXCEPTION 'Boarding status and stay record must agree' USING ERRCODE='23514';
 END IF;
 SELECT * INTO a FROM public.boarding_allocations WHERE id=s.allocation_id;
 IF b.status IN ('CHECKED_IN','STAYING') THEN
   IF a.released_at IS NOT NULL OR a.starts_on<>b.boarding_start OR a.ends_on<>b.boarding_end THEN
     RAISE EXCEPTION 'Active stay must retain its matching allocation' USING ERRCODE='23514';
   END IF;
 ELSE
   IF a.released_at IS DISTINCT FROM s.checked_out_at OR a.released_by_user_id IS DISTINCT FROM s.checked_out_by_user_id THEN
     RAISE EXCEPTION 'Check-out must preserve its attributed allocation release' USING ERRCODE='23514';
   END IF;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_CHECKED_IN'
     AND old_status='CONFIRMED' AND new_status IN ('CHECKED_IN','STAYING') AND actor_user_id=s.checked_in_by_user_id AND created_at=s.checked_in_at)
    OR (s.stay_started_at IS NOT NULL AND NOT (EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_CHECKED_IN' AND new_status='STAYING' AND s.stay_started_at=s.checked_in_at AND s.stay_started_by_user_id=s.checked_in_by_user_id) OR EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_STAY_STARTED'
     AND old_status='CHECKED_IN' AND new_status='STAYING' AND actor_user_id=s.stay_started_by_user_id AND created_at=s.stay_started_at)))
    OR (s.checked_out_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_CHECKED_OUT'
     AND old_status='STAYING' AND new_status IN ('CHECKED_OUT','COMPLETED') AND actor_user_id=s.checked_out_by_user_id AND created_at=s.checked_out_at))
    OR (s.completed_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_COMPLETED'
     AND old_status IN ('CHECKED_OUT','STAYING') AND new_status='COMPLETED' AND actor_user_id=s.completed_by_user_id AND created_at=s.completed_at)) THEN
   RAISE EXCEPTION 'Attributed Boarding lifecycle event required' USING ERRCODE='23514';
 END IF;
 IF EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND
    ((event_type='BOARDING_STAY_STARTED' AND s.stay_started_at IS NULL) OR
     (event_type='BOARDING_CHECKED_OUT' AND s.checked_out_at IS NULL) OR
     (event_type='BOARDING_COMPLETED' AND s.completed_at IS NULL))) THEN
   RAISE EXCEPTION 'Event cannot precede its operational step' USING ERRCODE='23514';
 END IF;
 IF EXISTS (SELECT 1 FROM public.boarding_notes n JOIN public.booking_events e ON e.id=n.event_id WHERE n.stay_id=s.id
    AND (e.booking_id<>which OR e.event_type<>'BOARDING_STAY_UPDATED' OR e.actor_user_id<>n.actor_user_id
      OR e.created_at<>n.created_at OR e.old_status::text IS DISTINCT FROM e.new_status::text
      OR e.new_status NOT IN ('CHECKED_IN','STAYING') OR e.new_status IS NULL
      OR (e.details->>'boarding_note_id') IS DISTINCT FROM n.id::text
      OR (s.checked_out_at IS NOT NULL AND n.created_at>s.checked_out_at)))
    OR EXISTS (SELECT 1 FROM public.booking_events e WHERE e.booking_id=which AND e.event_type='BOARDING_STAY_UPDATED'
       AND NOT EXISTS (SELECT 1 FROM public.boarding_notes n WHERE n.event_id=e.id AND n.stay_id=s.id)) THEN
   RAISE EXCEPTION 'Stay note and attributed event must agree' USING ERRCODE='23514';
 END IF;
END $$;
