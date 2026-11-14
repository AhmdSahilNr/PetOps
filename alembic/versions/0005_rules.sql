-- Extend reservation validity through active Boarding; preserve original 0003.
CREATE OR REPLACE FUNCTION petops_validate_confirmation(which uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.bookings WHERE id=which;
 IF NOT FOUND THEN RETURN; END IF;
 IF EXISTS (SELECT 1 FROM public.boarding_allocations a WHERE a.booking_id=b.id AND a.released_at IS NULL
   AND (b.booking_type<>'BOARDING' OR b.status NOT IN ('SUBMITTED','CONFIRMED','CHECKED_IN','STAYING')
     OR a.starts_on<>b.boarding_start OR a.ends_on<>b.boarding_end)) THEN
   RAISE EXCEPTION 'Release obsolete allocation before changing booking schedule/state' USING ERRCODE='23514';
 END IF;
 IF b.booking_type='BOARDING' AND b.status IN ('CHECKED_IN','STAYING') AND NOT EXISTS
    (SELECT 1 FROM public.boarding_allocations a JOIN public.accommodations u ON u.id=a.accommodation_id
     WHERE a.booking_id=b.id AND a.released_at IS NULL AND u.is_active
       AND a.starts_on=b.boarding_start AND a.ends_on=b.boarding_end) THEN
   RAISE EXCEPTION 'Active Boarding must retain matching accommodation' USING ERRCODE='23514';
 END IF;
 IF b.status<>'CONFIRMED' THEN RETURN; END IF;
 IF NOT EXISTS (SELECT 1 FROM public.services WHERE id=b.service_id AND is_active) THEN
   RAISE EXCEPTION 'BR-002: active service required' USING ERRCODE='23514';
 END IF;
 IF b.booking_type='GROOMING' THEN
   IF b.grooming_duration_minutes IS NULL OR b.assigned_staff_user_id IS NULL OR b.staff_start IS NULL
      OR b.grooming_start<=statement_timestamp() THEN
     RAISE EXCEPTION 'BR-002: eligible Grooming assignment and future schedule required' USING ERRCODE='23514';
   END IF;
 ELSIF b.boarding_start < (statement_timestamp() AT TIME ZONE 'Asia/Kuala_Lumpur')::date
    OR NOT EXISTS (SELECT 1 FROM public.boarding_allocations a JOIN public.accommodations u ON u.id=a.accommodation_id
      WHERE a.booking_id=b.id AND a.released_at IS NULL AND u.is_active
        AND a.starts_on=b.boarding_start AND a.ends_on=b.boarding_end) THEN
   RAISE EXCEPTION 'BR-002: matching active Boarding allocation required' USING ERRCODE='23514';
 END IF;
 IF b.assigned_staff_user_id IS NOT NULL AND
   (b.staff_start IS NULL OR b.staff_end IS NULL OR NOT public.petops_staff_covers(b.assigned_staff_user_id,b.staff_start,b.staff_end)
     OR NOT EXISTS (SELECT 1 FROM public.users WHERE id=b.assigned_staff_user_id AND is_active AND role='STAFF')) THEN
   RAISE EXCEPTION 'BR-002: assigned Staff is no longer eligible' USING ERRCODE='23514';
 END IF;
END $$;

CREATE FUNCTION petops_require_boarding_actor(who uuid, assigned uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE eligible boolean;
BEGIN
 SELECT is_active AND (role='ADMIN' OR (role='STAFF' AND id=assigned)) INTO eligible
   FROM public.users WHERE id=who FOR SHARE;
 IF NOT coalesce(eligible,false) THEN
   RAISE EXCEPTION 'Boarding actor must be active assigned Staff or Admin' USING ERRCODE='23514';
 END IF;
END $$;

CREATE FUNCTION petops_boarding_occupied(unit uuid) RETURNS bigint LANGUAGE sql STABLE AS $$
 SELECT count(*) FROM public.boarding_stays s JOIN public.boarding_allocations a ON a.id=s.allocation_id
 WHERE a.accommodation_id=unit AND s.checked_out_at IS NULL
$$;

CREATE FUNCTION petops_guard_boarding_booking() RETURNS trigger LANGUAGE plpgsql AS $$
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
      ((OLD.status='CONFIRMED' AND NEW.status='CHECKED_IN') OR
       (OLD.status='CHECKED_IN' AND NEW.status='STAYING') OR
       (OLD.status='STAYING' AND NEW.status='CHECKED_OUT') OR
       (OLD.status='CHECKED_OUT' AND NEW.status='COMPLETED')) THEN
     RAISE EXCEPTION 'Invalid Boarding operational transition' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_boarding_booking BEFORE INSERT OR UPDATE ON bookings
 FOR EACH ROW EXECUTE FUNCTION petops_guard_boarding_booking();

CREATE FUNCTION petops_guard_boarding_stay() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; a public.boarding_allocations%ROWTYPE; actor uuid; acted timestamptz;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Boarding history cannot be deleted' USING ERRCODE='23514'; END IF;
 SELECT * INTO b FROM public.bookings WHERE id=NEW.booking_id FOR UPDATE;
 IF NOT FOUND OR b.booking_type<>'BOARDING' THEN
   RAISE EXCEPTION 'Stay requires a Boarding booking' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
   SELECT * INTO a FROM public.boarding_allocations WHERE id=NEW.allocation_id;
   IF NOT FOUND OR b.status<>'CHECKED_IN' OR a.booking_id<>b.id OR a.released_at IS NOT NULL
      OR a.starts_on<>b.boarding_start OR a.ends_on<>b.boarding_end
      OR NEW.stay_started_at IS NOT NULL OR NEW.checked_out_at IS NOT NULL OR NEW.completed_at IS NOT NULL
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
CREATE TRIGGER guard_boarding_stay BEFORE INSERT OR UPDATE OR DELETE ON boarding_stays
 FOR EACH ROW EXECUTE FUNCTION petops_guard_boarding_stay();

CREATE FUNCTION petops_boarding_physical_capacity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE unit uuid; places integer; available boolean;
BEGIN
 SELECT accommodation_id INTO unit FROM public.boarding_allocations WHERE id=NEW.allocation_id;
 -- A real shared-parent write serializes physical check-in at RC and RR.
 UPDATE public.accommodations SET reservation_version=reservation_version+1 WHERE id=unit
   RETURNING capacity,is_active INTO places,available;
 IF NEW.checked_out_at IS NULL AND (NOT coalesce(available,false) OR public.petops_boarding_occupied(unit)>places) THEN
   RAISE EXCEPTION 'Accommodation is physically full; overdue stays remain occupied until check-out' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER boarding_physical_capacity AFTER INSERT OR UPDATE ON boarding_stays
 FOR EACH ROW EXECUTE FUNCTION petops_boarding_physical_capacity();

CREATE FUNCTION petops_guard_boarding_unit_capacity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.capacity<>OLD.capacity AND NEW.capacity<public.petops_boarding_occupied(NEW.id) THEN
   RAISE EXCEPTION 'Capacity cannot be below physically occupied places' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_boarding_unit_capacity BEFORE UPDATE ON accommodations
 FOR EACH ROW EXECUTE FUNCTION petops_guard_boarding_unit_capacity();

CREATE FUNCTION petops_guard_boarding_note() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; admitted timestamptz;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Stay notes are append-only' USING ERRCODE='23514'; END IF;
 SELECT b1.* INTO b FROM public.bookings b1 JOIN public.boarding_stays s ON s.booking_id=b1.id
   WHERE s.id=NEW.stay_id FOR UPDATE OF b1;
 IF NOT FOUND OR b.status NOT IN ('CHECKED_IN','STAYING') THEN
   RAISE EXCEPTION 'Stay updates require active Boarding' USING ERRCODE='23514';
 END IF;
 SELECT checked_in_at INTO admitted FROM public.boarding_stays WHERE id=NEW.stay_id;
 IF NEW.created_at<admitted OR NEW.created_at>clock_timestamp() THEN
   RAISE EXCEPTION 'Actual active-stay note time required' USING ERRCODE='23514';
 END IF;
 PERFORM public.petops_require_boarding_actor(NEW.actor_user_id,b.assigned_staff_user_id);
 RETURN NEW;
END $$;
CREATE TRIGGER guard_boarding_note BEFORE INSERT OR UPDATE OR DELETE ON boarding_notes
 FOR EACH ROW EXECUTE FUNCTION petops_guard_boarding_note();

CREATE FUNCTION petops_validate_boarding(which uuid) RETURNS void LANGUAGE plpgsql AS $$
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
     AND old_status='CONFIRMED' AND new_status='CHECKED_IN' AND actor_user_id=s.checked_in_by_user_id AND created_at=s.checked_in_at)
    OR (s.stay_started_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_STAY_STARTED'
     AND old_status='CHECKED_IN' AND new_status='STAYING' AND actor_user_id=s.stay_started_by_user_id AND created_at=s.stay_started_at))
    OR (s.checked_out_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_CHECKED_OUT'
     AND old_status='STAYING' AND new_status='CHECKED_OUT' AND actor_user_id=s.checked_out_by_user_id AND created_at=s.checked_out_at))
    OR (s.completed_at IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='BOARDING_COMPLETED'
     AND old_status='CHECKED_OUT' AND new_status='COMPLETED' AND actor_user_id=s.completed_by_user_id AND created_at=s.completed_at)) THEN
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

CREATE FUNCTION petops_boarding_constraint() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE which uuid;
BEGIN
 IF TG_TABLE_NAME='bookings' THEN which:=NEW.id;
 ELSIF TG_TABLE_NAME='boarding_notes' THEN SELECT booking_id INTO which FROM public.boarding_stays WHERE id=NEW.stay_id;
 ELSE which:=NEW.booking_id; END IF;
 PERFORM public.petops_validate_boarding(which);
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER boarding_booking_consistency AFTER INSERT OR UPDATE ON bookings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_boarding_constraint();
CREATE CONSTRAINT TRIGGER boarding_stay_consistency AFTER INSERT OR UPDATE ON boarding_stays
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_boarding_constraint();
CREATE CONSTRAINT TRIGGER boarding_note_consistency AFTER INSERT OR UPDATE ON boarding_notes
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_boarding_constraint();
CREATE CONSTRAINT TRIGGER boarding_event_consistency AFTER INSERT OR UPDATE ON booking_events
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_boarding_constraint();
CREATE CONSTRAINT TRIGGER boarding_allocation_consistency AFTER INSERT OR UPDATE ON boarding_allocations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_boarding_constraint();
