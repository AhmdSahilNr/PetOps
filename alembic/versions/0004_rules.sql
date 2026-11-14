-- Normal runtime integrity. No SECURITY DEFINER and no HTTP-actor inference.
CREATE FUNCTION petops_guard_grooming_booking() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.booking_type='GROOMING' AND NEW.status IN ('IN_PROGRESS','COMPLETED') THEN
     RAISE EXCEPTION 'Grooming must progress from confirmed work' USING ERRCODE='23514';
   END IF;
   RETURN NEW;
 END IF;
 IF NEW.booking_type='GROOMING' AND NEW.status IN ('IN_PROGRESS','COMPLETED')
    AND OLD.booking_type<>'GROOMING' THEN
   RAISE EXCEPTION 'Cannot convert Boarding into operational Grooming' USING ERRCODE='23514';
 END IF;
 IF OLD.booking_type='GROOMING' AND
   (OLD.status IN ('IN_PROGRESS','COMPLETED') OR NEW.status IN ('IN_PROGRESS','COMPLETED')) THEN
   IF (NEW.customer_id,NEW.pet_id,NEW.service_id,NEW.booking_type,NEW.grooming_start,
       NEW.grooming_duration_minutes,NEW.assigned_staff_user_id,NEW.staff_start,NEW.staff_end,
       NEW.created_by_user_id,NEW.created_at)
      IS DISTINCT FROM
      (OLD.customer_id,OLD.pet_id,OLD.service_id,OLD.booking_type,OLD.grooming_start,
       OLD.grooming_duration_minutes,OLD.assigned_staff_user_id,OLD.staff_start,OLD.staff_end,
       OLD.created_by_user_id,OLD.created_at) THEN
     RAISE EXCEPTION 'Operational Grooming links, assignment and schedule are preserved' USING ERRCODE='23514';
   END IF;
   IF NEW.status<>OLD.status AND NOT
      ((OLD.status='CONFIRMED' AND NEW.status='IN_PROGRESS') OR
       (OLD.status='IN_PROGRESS' AND NEW.status='COMPLETED')) THEN
     RAISE EXCEPTION 'Invalid Grooming operational transition' USING ERRCODE='23514';
   END IF;
   IF NEW.assigned_staff_user_id IS NULL OR NEW.grooming_duration_minutes IS NULL THEN
     RAISE EXCEPTION 'Confirmed Staff and duration required for Grooming work' USING ERRCODE='23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_grooming_booking BEFORE INSERT OR UPDATE ON bookings
 FOR EACH ROW EXECUTE FUNCTION petops_guard_grooming_booking();

CREATE FUNCTION petops_guard_grooming_record() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; actor uuid; eligible boolean;
BEGIN
 IF TG_OP='DELETE' THEN
   RAISE EXCEPTION 'Grooming history cannot be deleted' USING ERRCODE='23514';
 END IF;
 SELECT * INTO b FROM public.bookings WHERE id=NEW.booking_id FOR UPDATE;
 IF NOT FOUND OR b.booking_type<>'GROOMING' THEN
   RAISE EXCEPTION 'Grooming record needs a Grooming booking' USING ERRCODE='23514';
 END IF;
 IF TG_OP='INSERT' THEN
   IF b.status<>'IN_PROGRESS' OR NEW.completed_at IS NOT NULL
      OR NEW.started_at>clock_timestamp() OR NEW.started_at<b.created_at THEN
     RAISE EXCEPTION 'Start record must match in-progress work and actual start time' USING ERRCODE='23514';
   END IF;
   actor:=NEW.started_by_user_id;
 ELSE
   IF (NEW.id,NEW.booking_id,NEW.started_by_user_id,NEW.started_at)
      IS DISTINCT FROM (OLD.id,OLD.booking_id,OLD.started_by_user_id,OLD.started_at)
      OR OLD.completed_at IS NOT NULL OR NEW.completed_at IS NULL
      OR NEW.completed_at>clock_timestamp() OR b.status<>'COMPLETED' THEN
     RAISE EXCEPTION 'Only one attributed completion is allowed; history is retained' USING ERRCODE='23514';
   END IF;
   actor:=NEW.completed_by_user_id;
 END IF;
 SELECT is_active AND (role='ADMIN' OR (role='STAFF' AND id=b.assigned_staff_user_id))
   INTO eligible FROM public.users WHERE id=actor FOR SHARE;
 IF NOT coalesce(eligible,false) THEN
   RAISE EXCEPTION 'Grooming actor must be active assigned Staff or Admin' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_grooming_record BEFORE INSERT OR UPDATE OR DELETE ON grooming_records
 FOR EACH ROW EXECUTE FUNCTION petops_guard_grooming_record();

CREATE FUNCTION petops_guard_grooming_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.event_type IN ('GROOMING_STARTED','GROOMING_COMPLETED') THEN
   RAISE EXCEPTION 'Grooming operational events are immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_grooming_event BEFORE UPDATE OR DELETE ON booking_events
 FOR EACH ROW EXECUTE FUNCTION petops_guard_grooming_event();

CREATE FUNCTION petops_validate_grooming(which uuid) RETURNS void LANGUAGE plpgsql AS $$
DECLARE b public.bookings%ROWTYPE; r public.grooming_records%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.bookings WHERE id=which;
 IF NOT FOUND THEN RETURN; END IF;
 SELECT * INTO r FROM public.grooming_records WHERE booking_id=which;
 IF NOT FOUND THEN
   IF (b.booking_type='GROOMING' AND b.status IN ('IN_PROGRESS','COMPLETED'))
      OR EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which
          AND event_type IN ('GROOMING_STARTED','GROOMING_COMPLETED')) THEN
     RAISE EXCEPTION 'Operational Grooming record required' USING ERRCODE='23514';
   END IF;
   RETURN;
 END IF;
 IF b.booking_type<>'GROOMING' OR b.status NOT IN ('IN_PROGRESS','COMPLETED')
    OR (b.status='IN_PROGRESS' AND r.completed_at IS NOT NULL)
    OR (b.status='COMPLETED' AND r.completed_at IS NULL) THEN
   RAISE EXCEPTION 'Grooming status and completion record must agree' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM public.booking_events WHERE booking_id=which
     AND event_type='GROOMING_STARTED' AND old_status='CONFIRMED' AND new_status='IN_PROGRESS'
     AND actor_user_id=r.started_by_user_id AND created_at=r.started_at) THEN
   RAISE EXCEPTION 'Attributed Grooming start event required' USING ERRCODE='23514';
 END IF;
 IF r.completed_at IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM public.booking_events WHERE booking_id=which AND event_type='GROOMING_COMPLETED'
     AND old_status='IN_PROGRESS' AND new_status='COMPLETED'
     AND actor_user_id=r.completed_by_user_id AND created_at=r.completed_at) THEN
   RAISE EXCEPTION 'Attributed Grooming completion event required' USING ERRCODE='23514';
 END IF;
 IF r.completed_at IS NULL AND EXISTS (SELECT 1 FROM public.booking_events
     WHERE booking_id=which AND event_type='GROOMING_COMPLETED') THEN
   RAISE EXCEPTION 'Completion event requires completed service' USING ERRCODE='23514';
 END IF;
END $$;
CREATE FUNCTION petops_grooming_constraint() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='bookings' THEN PERFORM public.petops_validate_grooming(NEW.id);
 ELSE PERFORM public.petops_validate_grooming(NEW.booking_id); END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER grooming_booking_consistency AFTER INSERT OR UPDATE ON bookings
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_grooming_constraint();
CREATE CONSTRAINT TRIGGER grooming_record_consistency AFTER INSERT OR UPDATE ON grooming_records
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_grooming_constraint();
CREATE CONSTRAINT TRIGGER grooming_event_consistency AFTER INSERT OR UPDATE ON booking_events
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION petops_grooming_constraint();
