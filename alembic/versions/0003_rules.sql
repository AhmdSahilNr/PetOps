-- Database guards supplement API authorization. No trigger infers the HTTP actor.
-- Every function uses qualified tables; no SECURITY DEFINER privileges are used.

CREATE FUNCTION petops_staff_covers(who uuid, lo timestamptz, hi timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT coalesce((SELECT range_agg(tstzrange(starts_at,ends_at,'[)')) @> tstzrange(lo,hi,'[)')
   FROM public.staff_availability WHERE staff_user_id=who AND is_active),false)
$$;

CREATE FUNCTION petops_capacity_peak(unit uuid) RETURNS bigint LANGUAGE sql STABLE AS $$
 SELECT coalesce(max(used),0) FROM (
   SELECT sum(delta) OVER (ORDER BY day ROWS UNBOUNDED PRECEDING) AS used FROM (
     SELECT day,sum(delta) AS delta FROM (
       SELECT starts_on AS day,1 AS delta FROM public.boarding_allocations
         WHERE accommodation_id=unit AND released_at IS NULL
       UNION ALL
       SELECT ends_on AS day,-1 AS delta FROM public.boarding_allocations
         WHERE accommodation_id=unit AND released_at IS NULL
     ) edges GROUP BY day
   ) grouped_edges
 ) occupancy
$$;

CREATE FUNCTION petops_guard_booking_resources() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE active_staff boolean; configured integer; needs_duration boolean;
BEGIN
 IF TG_OP='INSERT' THEN needs_duration := true;
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
       OR NOT public.petops_staff_covers(NEW.assigned_staff_user_id,NEW.staff_start,NEW.staff_end) THEN
     RAISE EXCEPTION 'Active available Staff required for the entire work period' USING ERRCODE='23514';
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
CREATE TRIGGER guard_booking_resources BEFORE INSERT OR UPDATE ON bookings
 FOR EACH ROW EXECUTE FUNCTION petops_guard_booking_resources();

CREATE FUNCTION petops_validate_confirmation(which uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.bookings WHERE id=which;
 IF NOT FOUND THEN RETURN; END IF;
 IF EXISTS (SELECT 1 FROM public.boarding_allocations a WHERE a.booking_id=b.id AND a.released_at IS NULL
   AND (b.booking_type<>'BOARDING' OR b.status NOT IN ('SUBMITTED','CONFIRMED')
     OR a.starts_on<>b.boarding_start OR a.ends_on<>b.boarding_end)) THEN
   RAISE EXCEPTION 'Release obsolete allocation before changing booking schedule/state' USING ERRCODE='23514';
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
CREATE FUNCTION petops_confirmation_constraint() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='bookings' THEN PERFORM public.petops_validate_confirmation(NEW.id);
 ELSE PERFORM public.petops_validate_confirmation(NEW.booking_id); END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER booking_confirmation_prerequisites AFTER INSERT OR UPDATE ON bookings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_confirmation_constraint();
CREATE CONSTRAINT TRIGGER allocation_confirmation_prerequisites AFTER INSERT OR UPDATE ON boarding_allocations
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_confirmation_constraint();

CREATE FUNCTION petops_guard_availability() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE who uuid;
BEGIN
 IF TG_OP='UPDATE' AND NEW.staff_user_id<>OLD.staff_user_id THEN
   RAISE EXCEPTION 'Availability owner is immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN who:=OLD.staff_user_id; ELSE who:=NEW.staff_user_id; END IF;
 UPDATE public.users SET scheduling_version=scheduling_version+1 WHERE id=who;
 IF EXISTS (SELECT 1 FROM public.bookings b WHERE b.assigned_staff_user_id=who
     AND b.status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING')
     AND (b.staff_start IS NULL OR NOT public.petops_staff_covers(who,b.staff_start,b.staff_end))) THEN
   RAISE EXCEPTION 'Availability change would invalidate assigned work' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER guard_staff_availability AFTER INSERT OR UPDATE OR DELETE ON staff_availability
 FOR EACH ROW EXECUTE FUNCTION petops_guard_availability();
CREATE FUNCTION petops_guard_staff_account() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.is_active,NEW.role) IS DISTINCT FROM (OLD.is_active,OLD.role)
   AND (NOT NEW.is_active OR NEW.role<>'STAFF')
   AND EXISTS (SELECT 1 FROM public.bookings WHERE assigned_staff_user_id=OLD.id
     AND status IN ('SUBMITTED','CONFIRMED','IN_PROGRESS','CHECKED_IN','STAYING')) THEN
   RAISE EXCEPTION 'Release or reassign active work before deactivating Staff' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_staff_account BEFORE UPDATE ON users
 FOR EACH ROW EXECUTE FUNCTION petops_guard_staff_account();

CREATE FUNCTION petops_guard_allocation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Allocation history cannot be deleted' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
   IF (NEW.id,NEW.booking_id,NEW.accommodation_id,NEW.starts_on,NEW.ends_on,NEW.created_by_user_id,NEW.created_at)
     IS DISTINCT FROM (OLD.id,OLD.booking_id,OLD.accommodation_id,OLD.starts_on,OLD.ends_on,OLD.created_by_user_id,OLD.created_at)
     OR OLD.released_at IS NOT NULL OR NEW.released_at IS NULL THEN
     RAISE EXCEPTION 'Allocation is immutable except for a single attributed release' USING ERRCODE='23514';
   END IF;
 ELSE
   SELECT * INTO b FROM public.bookings WHERE id=NEW.booking_id FOR UPDATE;
   IF NOT FOUND OR b.booking_type<>'BOARDING' OR b.status NOT IN ('SUBMITTED','CONFIRMED')
      OR NEW.starts_on<>b.boarding_start OR NEW.ends_on<>b.boarding_end OR NEW.released_at IS NOT NULL THEN
     RAISE EXCEPTION 'Allocation must match a changeable Boarding booking' USING ERRCODE='23514';
   END IF;
   IF NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.created_by_user_id AND role='ADMIN' AND is_active) THEN
     RAISE EXCEPTION 'Allocation actor must be active Admin' USING ERRCODE='23514';
   END IF;
   IF NOT EXISTS (SELECT 1 FROM public.accommodations WHERE id=NEW.accommodation_id AND is_active) THEN
     RAISE EXCEPTION 'Active accommodation required' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_boarding_allocation BEFORE INSERT OR UPDATE OR DELETE ON boarding_allocations
 FOR EACH ROW EXECUTE FUNCTION petops_guard_allocation();
CREATE FUNCTION petops_allocation_capacity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE limit_places integer; available boolean;
BEGIN
 UPDATE public.accommodations SET reservation_version=reservation_version+1
   WHERE id=NEW.accommodation_id RETURNING capacity,is_active INTO limit_places,available;
 IF NEW.released_at IS NULL AND (NOT coalesce(available,false) OR public.petops_capacity_peak(NEW.accommodation_id)>limit_places) THEN
   RAISE EXCEPTION 'Configured accommodation capacity exceeded' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER allocation_capacity AFTER INSERT OR UPDATE ON boarding_allocations
 FOR EACH ROW EXECUTE FUNCTION petops_allocation_capacity();
CREATE FUNCTION petops_guard_accommodation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.capacity<>OLD.capacity AND public.petops_capacity_peak(NEW.id)>NEW.capacity THEN
   RAISE EXCEPTION 'Capacity reduction would invalidate active allocations' USING ERRCODE='23514';
 END IF;
 IF OLD.is_active AND NOT NEW.is_active AND EXISTS
   (SELECT 1 FROM public.boarding_allocations WHERE accommodation_id=NEW.id AND released_at IS NULL) THEN
   RAISE EXCEPTION 'Release or reallocate active allocations before deactivation' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_accommodation BEFORE UPDATE ON accommodations
 FOR EACH ROW EXECUTE FUNCTION petops_guard_accommodation();
