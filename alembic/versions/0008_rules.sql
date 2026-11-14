-- Controlled D changes. Original migration files and history remain unchanged.
CREATE OR REPLACE FUNCTION petops_guard_staff_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.is_active,NEW.role) IS DISTINCT FROM (OLD.is_active,OLD.role) AND (NOT NEW.is_active OR NEW.role<>'STAFF') AND
  (EXISTS (SELECT 1 FROM public.staff_responsibilities r JOIN public.bookings b ON b.id=r.booking_id
   WHERE r.staff_user_id=OLD.id AND r.released_at IS NULL AND
    (coalesce(r.ended_at,r.ends_at)>clock_timestamp() OR (r.ended_at IS NULL AND r.starts_at<=clock_timestamp() AND b.status IN ('IN_PROGRESS','CHECKED_IN','STAYING'))))
   OR EXISTS (SELECT 1 FROM public.bookings WHERE assigned_staff_user_id=OLD.id AND status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING') AND staff_end IS NULL)) THEN
   RAISE EXCEPTION 'Reassign or finish current/upcoming work before deactivating Staff' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;

-- Generic availability is compatibility data, no longer an assignment rule.
CREATE OR REPLACE FUNCTION petops_guard_availability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND NEW.staff_user_id<>OLD.staff_user_id THEN RAISE EXCEPTION 'Legacy availability owner is immutable' USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;

CREATE FUNCTION petops_require_responsible_actor(who uuid, which uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE staff uuid; eligible boolean;
BEGIN
 SELECT r.staff_user_id INTO staff FROM public.staff_responsibilities r
 WHERE r.booking_id=which AND (r.released_at IS NULL OR r.released_at>=transaction_timestamp()) AND r.starts_at<=clock_timestamp()
  AND (coalesce(r.ended_at,r.ends_at)>clock_timestamp() OR r.ended_at IS NULL)
 ORDER BY r.starts_at DESC,r.created_at DESC LIMIT 1;
 IF staff IS NULL THEN
  SELECT r.staff_user_id INTO staff FROM public.staff_responsibilities r JOIN public.bookings b ON b.id=r.booking_id
   WHERE r.booking_id=which AND (r.released_at IS NULL OR r.released_at>=transaction_timestamp()) AND r.created_by_user_id IS NULL AND r.ended_at IS NULL
    AND b.assigned_staff_user_id=r.staff_user_id AND b.status IN ('SUBMITTED','CONFIRMED','CHECKED_IN','STAYING','COMPLETED')
   ORDER BY r.created_at DESC LIMIT 1;
 END IF;
 IF staff IS NULL AND EXISTS (SELECT 1 FROM public.boarding_stays WHERE booking_id=which AND checked_out_at IS NOT NULL) THEN
  SELECT assigned_staff_user_id INTO staff FROM public.bookings WHERE id=which AND status='COMPLETED';
 END IF;
 SELECT is_active AND (role='ADMIN' OR (role='STAFF' AND id=staff)) INTO eligible FROM public.users WHERE id=who FOR SHARE;
 IF NOT coalesce(eligible,false) THEN RAISE EXCEPTION 'Current responsible Staff or Admin required' USING ERRCODE='23514'; END IF;
END $$;

CREATE FUNCTION petops_guard_responsibility() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Responsibility history is retained' USING ERRCODE='23514'; END IF;
 SELECT * INTO b FROM public.bookings WHERE id=NEW.booking_id FOR UPDATE;
 IF TG_OP='INSERT' THEN
  UPDATE public.users SET scheduling_version=scheduling_version+1 WHERE id=NEW.staff_user_id;
  IF NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.created_by_user_id AND role='ADMIN' AND is_active)
   OR NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.staff_user_id AND role='STAFF' AND is_active)
   OR b.status NOT IN ('SUBMITTED','CONFIRMED','CHECKED_IN','STAYING')
   OR NEW.created_at>clock_timestamp() OR NEW.released_at IS NOT NULL OR NEW.ended_at IS NOT NULL THEN
   RAISE EXCEPTION 'New responsibility requires active Staff, Admin attribution and live work' USING ERRCODE='23514';
  END IF;
  IF b.booking_type='GROOMING' AND (NEW.starts_at<>b.grooming_start OR NEW.ends_at<>b.grooming_start+b.grooming_duration_minutes*interval '1 minute') THEN
   RAISE EXCEPTION 'Grooming responsibility inherits booking timing' USING ERRCODE='23514';
  ELSIF b.booking_type='BOARDING' AND (NEW.starts_at<(b.boarding_start::timestamp AT TIME ZONE 'Asia/Kuala_Lumpur') OR NEW.ends_at>(b.boarding_end::timestamp AT TIME ZONE 'Asia/Kuala_Lumpur')) THEN
   RAISE EXCEPTION 'Responsibility must remain inside the stay' USING ERRCODE='23514';
  END IF;
 ELSE
  IF (NEW.id,NEW.booking_id,NEW.staff_user_id,NEW.starts_at,NEW.ends_at,NEW.created_by_user_id,NEW.created_at)
    IS DISTINCT FROM (OLD.id,OLD.booking_id,OLD.staff_user_id,OLD.starts_at,OLD.ends_at,OLD.created_by_user_id,OLD.created_at)
    OR (OLD.ended_at IS NOT NULL AND (NEW.ended_at,NEW.ended_by_user_id) IS DISTINCT FROM (OLD.ended_at,OLD.ended_by_user_id))
    OR (OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at) THEN
   RAISE EXCEPTION 'Original responsibility facts are immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.ended_at IS DISTINCT FROM OLD.ended_at AND NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.ended_by_user_id AND is_active AND role='ADMIN') THEN
   RAISE EXCEPTION 'Admin attribution required for handover' USING ERRCODE='23514';
  END IF;
  IF NEW.released_at IS DISTINCT FROM OLD.released_at AND b.status IN ('CHECKED_IN','STAYING') AND OLD.starts_at<clock_timestamp() THEN
   RAISE EXCEPTION 'End current responsibility through an attributed handover; do not withdraw it' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_responsibility BEFORE INSERT OR UPDATE OR DELETE ON staff_responsibilities
 FOR EACH ROW EXECUTE FUNCTION petops_guard_responsibility();

CREATE FUNCTION petops_release_responsibilities() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status IN ('COMPLETED','CHECKED_OUT','CANCELLED','REJECTED') THEN
  UPDATE public.staff_responsibilities SET released_at=clock_timestamp() WHERE booking_id=NEW.id AND released_at IS NULL;
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER release_responsibilities AFTER UPDATE OF status ON bookings FOR EACH ROW EXECUTE FUNCTION petops_release_responsibilities();

CREATE FUNCTION petops_validate_responsibility() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; which uuid; lastrow public.staff_responsibilities%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='bookings' THEN which:=NEW.id; ELSE which:=NEW.booking_id; END IF;
 SELECT * INTO b FROM public.bookings WHERE id=which;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF b.status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING') AND b.assigned_staff_user_id IS NULL
  AND EXISTS (SELECT 1 FROM public.staff_responsibilities WHERE booking_id=which AND released_at IS NULL) THEN
  RAISE EXCEPTION 'Live responsibility requires a matching booking Staff snapshot' USING ERRCODE='23514';
 END IF;
 IF EXISTS (SELECT 1 FROM public.staff_responsibilities r WHERE r.booking_id=which AND r.released_at IS NULL AND r.ended_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.staff_responsibilities nextrow WHERE nextrow.booking_id=which AND nextrow.released_at IS NULL AND nextrow.starts_at=r.ended_at)) THEN
  RAISE EXCEPTION 'Effective handover end must match the next responsibility start' USING ERRCODE='23514';
 END IF;
 IF b.status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING') AND b.assigned_staff_user_id IS NOT NULL AND b.staff_start IS NOT NULL THEN
  SELECT * INTO lastrow FROM public.staff_responsibilities WHERE booking_id=which AND released_at IS NULL ORDER BY starts_at DESC,created_at DESC LIMIT 1;
  IF NOT FOUND OR (lastrow.staff_user_id,lastrow.starts_at,lastrow.ends_at) IS DISTINCT FROM (b.assigned_staff_user_id,b.staff_start,b.staff_end) THEN
   RAISE EXCEPTION 'Booking and latest responsibility must agree' USING ERRCODE='23514';
  END IF;
 END IF;
 IF EXISTS (SELECT 1 FROM public.staff_responsibilities r WHERE r.booking_id=which AND r.created_by_user_id IS NOT NULL AND NOT EXISTS
   (SELECT 1 FROM public.booking_events e WHERE e.booking_id=which AND e.event_type='STAFF_ASSIGNED' AND e.actor_user_id=r.created_by_user_id AND e.details->>'responsibility_id'=r.id::text)) THEN
   RAISE EXCEPTION 'Attributed assignment event required' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER responsibility_booking_consistency AFTER INSERT OR UPDATE ON bookings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_validate_responsibility();
CREATE CONSTRAINT TRIGGER responsibility_period_consistency AFTER INSERT OR UPDATE ON staff_responsibilities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_validate_responsibility();

CREATE OR REPLACE FUNCTION petops_staff_notice_kind(which uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN e.event_type IN ('STAFF_ASSIGNED','STAFF_UNASSIGNED','BOOKING_RESCHEDULED','BOOKING_CANCELLED','STATUS_CHANGED')
  AND (e.old_assigned_staff_user_id IS DISTINCT FROM e.new_assigned_staff_user_id OR (e.details->'old_work')::jsonb IS DISTINCT FROM (e.details->'new_work')::jsonb)
  AND (e.new_assigned_staff_user_id IS NOT NULL OR e.old_assigned_staff_user_id IS NOT NULL)
 THEN CASE WHEN e.old_assigned_staff_user_id IS NULL THEN 'STAFF_ASSIGNED' ELSE 'STAFF_REASSIGNED' END ELSE NULL END
 FROM public.booking_events e WHERE e.id=which
$$;


CREATE OR REPLACE FUNCTION petops_guard_booking_resources() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE active_staff boolean; configured integer; needs_duration boolean;
BEGIN
 IF TG_OP='INSERT' THEN
   IF NOT EXISTS (SELECT 1 FROM public.pets WHERE id=NEW.pet_id AND is_active) THEN RAISE EXCEPTION 'Choose an active pet' USING ERRCODE='23514'; END IF;
   needs_duration := true;
 ELSE needs_duration := (NEW.service_id,NEW.grooming_start,NEW.grooming_duration_minutes)
   IS DISTINCT FROM (OLD.service_id,OLD.grooming_start,OLD.grooming_duration_minutes);
 END IF;
 IF NEW.booking_type='GROOMING' AND needs_duration THEN
   SELECT duration_minutes INTO configured FROM public.services WHERE id=NEW.service_id;
   IF NEW.grooming_duration_minutes IS NULL OR configured IS NULL OR NEW.grooming_duration_minutes<>configured THEN
     RAISE EXCEPTION 'Configured Grooming duration required' USING ERRCODE='23514';
   END IF;
 END IF;
 IF NEW.assigned_staff_user_id IS NOT NULL AND NEW.status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING') THEN
   -- A real write serializes assignment against availability/account changes,
   -- including REPEATABLE READ transactions (which abort on a stale row).
   UPDATE public.users SET scheduling_version=scheduling_version+1 WHERE id=NEW.assigned_staff_user_id;
   IF EXISTS (SELECT 1 FROM public.bookings WHERE id<>NEW.id AND assigned_staff_user_id=NEW.assigned_staff_user_id
     AND status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING')
     AND (staff_start IS NULL OR staff_end IS NULL)) THEN
     RAISE EXCEPTION 'Repair legacy assigned work with an unknown period before assigning more work' USING ERRCODE='23514';
   END IF;
   SELECT is_active AND role='STAFF' INTO active_staff FROM public.users WHERE id=NEW.assigned_staff_user_id;
   IF NOT coalesce(active_staff,false) OR NEW.staff_start IS NULL OR NEW.staff_end IS NULL
 THEN
     RAISE EXCEPTION 'Active Staff and a recorded booking period required' USING ERRCODE='23514';
   END IF;
   IF NEW.booking_type='GROOMING' THEN
     IF NEW.grooming_duration_minutes IS NULL OR NEW.staff_start<>NEW.grooming_start
        OR NEW.staff_end<>NEW.grooming_start+NEW.grooming_duration_minutes*interval '1 minute' THEN
       RAISE EXCEPTION 'Staff window must match requested Grooming duration' USING ERRCODE='23514';
     END IF;
   ELSIF NEW.staff_start < (NEW.boarding_start::timestamp AT TIME ZONE 'Asia/Kuala_Lumpur')
      OR NEW.staff_end > (NEW.boarding_end::timestamp AT TIME ZONE 'Asia/Kuala_Lumpur') THEN
     RAISE EXCEPTION 'Boarding duty window must be inside the stay' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;

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
   (b.staff_start IS NULL OR b.staff_end IS NULL
     OR NOT EXISTS (SELECT 1 FROM public.users WHERE id=b.assigned_staff_user_id AND is_active AND role='STAFF')) THEN
   RAISE EXCEPTION 'BR-002: assigned Staff is no longer eligible' USING ERRCODE='23514';
 END IF;
END $$;

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
       NEW.created_by_user_id,NEW.created_at)
      IS DISTINCT FROM
      (OLD.customer_id,OLD.pet_id,OLD.service_id,OLD.booking_type,OLD.boarding_start,OLD.boarding_end,
       OLD.created_by_user_id,OLD.created_at) THEN
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
 PERFORM public.petops_require_responsible_actor(actor,b.id);
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION petops_guard_boarding_note() RETURNS trigger LANGUAGE plpgsql AS $$
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
 PERFORM public.petops_require_responsible_actor(NEW.actor_user_id,b.id);
 RETURN NEW;
END $$;
