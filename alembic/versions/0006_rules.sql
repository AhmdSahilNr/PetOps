-- Only approved in-system notices; no external delivery or historical backfill.
CREATE FUNCTION petops_reminder_reference(which uuid) RETURNS timestamptz LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN booking_type='GROOMING' THEN grooming_start
   ELSE boarding_start::timestamp AT TIME ZONE 'Asia/Kuala_Lumpur' END
 FROM public.bookings WHERE id=which
$$;

CREATE FUNCTION petops_customer_notice_kind(which uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT CASE e.event_type
   WHEN 'BOOKING_SUBMITTED' THEN 'BOOKING_SUBMITTED'
   WHEN 'BOOKING_RESCHEDULED' THEN 'BOOKING_RESCHEDULED'
   WHEN 'BOOKING_CANCELLED' THEN 'BOOKING_CANCELLED'
   WHEN 'STATUS_CHANGED' THEN CASE
     WHEN e.new_status='CONFIRMED' THEN CASE WHEN EXISTS
       (SELECT 1 FROM public.booking_events r WHERE r.booking_id=e.booking_id
        AND r.event_type='BOOKING_RESCHEDULED' AND r.created_at<=e.created_at)
       THEN 'BOOKING_RECONFIRMED' ELSE 'BOOKING_CONFIRMED' END
     WHEN e.new_status='REJECTED' THEN CASE WHEN EXISTS
       (SELECT 1 FROM public.booking_events r WHERE r.booking_id=e.booking_id
        AND r.event_type='BOOKING_RESCHEDULED' AND r.created_at<=e.created_at)
       THEN 'RESCHEDULE_REJECTED' ELSE 'BOOKING_REJECTED' END
     ELSE NULL END
   ELSE NULL END
 FROM public.booking_events e WHERE e.id=which
$$;

CREATE FUNCTION petops_staff_notice_kind(which uuid) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT CASE WHEN e.event_type='STAFF_ASSIGNED' AND e.new_assigned_staff_user_id IS NOT NULL
   AND (e.old_assigned_staff_user_id IS DISTINCT FROM e.new_assigned_staff_user_id
     OR (e.details->'old_work')::jsonb IS DISTINCT FROM (e.details->'new_work')::jsonb)
   THEN CASE WHEN e.old_assigned_staff_user_id IS NULL THEN 'STAFF_ASSIGNED' ELSE 'STAFF_REASSIGNED' END
   ELSE NULL END
 FROM public.booking_events e WHERE e.id=which
$$;

CREATE FUNCTION petops_guard_notification() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE e public.booking_events%ROWTYPE; b public.bookings%ROWTYPE; owner_id uuid;
        expected text; cfg public.notification_settings%ROWTYPE; ref timestamptz; latest uuid;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Delivered notification history is retained' USING ERRCODE='23514'; END IF;
 IF TG_OP='UPDATE' THEN
   IF (NEW.id,NEW.recipient_user_id,NEW.recipient_role,NEW.booking_id,NEW.source_event_id,NEW.kind,
       NEW.created_at,NEW.schedule_reference,NEW.lead_minutes)
      IS DISTINCT FROM (OLD.id,OLD.recipient_user_id,OLD.recipient_role,OLD.booking_id,OLD.source_event_id,
       OLD.kind,OLD.created_at,OLD.schedule_reference,OLD.lead_minutes)
      OR OLD.read_at IS NOT NULL OR NEW.read_at IS NULL OR NEW.read_at>clock_timestamp() THEN
     RAISE EXCEPTION 'Only one attributed read-time update is allowed' USING ERRCODE='23514';
   END IF;
   RETURN NEW;
 END IF;
 SELECT * INTO e FROM public.booking_events WHERE id=NEW.source_event_id;
 SELECT * INTO b FROM public.bookings WHERE id=NEW.booking_id;
 SELECT user_id INTO owner_id FROM public.customers WHERE id=b.customer_id;
 IF e.id IS NULL OR b.id IS NULL OR e.booking_id<>b.id OR NEW.read_at IS NOT NULL
    OR NEW.created_at<e.created_at OR NEW.created_at>clock_timestamp()
    OR NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.recipient_user_id AND is_active AND role=NEW.recipient_role) THEN
   RAISE EXCEPTION 'Valid active recipient and true booking event required' USING ERRCODE='23514';
 END IF;
 IF NEW.kind='BOOKING_REMINDER' THEN
   SELECT * INTO cfg FROM public.notification_settings WHERE id=1;
   ref:=public.petops_reminder_reference(b.id);
   SELECT id INTO latest FROM public.booking_events WHERE booking_id=b.id AND event_type='STATUS_CHANGED'
     AND new_status='CONFIRMED' ORDER BY created_at DESC,id DESC LIMIT 1;
   IF NEW.recipient_role<>'CUSTOMER' OR NEW.recipient_user_id<>owner_id OR b.status<>'CONFIRMED'
      OR NOT cfg.enabled OR cfg.lead_minutes IS NULL OR latest IS DISTINCT FROM e.id
      OR NEW.schedule_reference IS DISTINCT FROM ref OR NEW.lead_minutes IS DISTINCT FROM cfg.lead_minutes
      OR ref<=clock_timestamp() OR ref-clock_timestamp()>cfg.lead_minutes*interval '1 minute' THEN
     RAISE EXCEPTION 'Reminder requires an eligible future confirmed booking and explicit configuration' USING ERRCODE='23514';
   END IF;
 ELSIF NEW.recipient_role='CUSTOMER' THEN
   expected:=public.petops_customer_notice_kind(e.id);
   IF expected IS NULL OR NEW.kind<>expected OR NEW.recipient_user_id<>owner_id THEN
     RAISE EXCEPTION 'Customer notification must belong to its booking owner and approved event' USING ERRCODE='23514';
   END IF;
 ELSIF NEW.recipient_role='STAFF' THEN
   expected:=public.petops_staff_notice_kind(e.id);
   IF expected IS NULL OR NEW.kind<>expected
      OR (NEW.recipient_user_id IS DISTINCT FROM e.new_assigned_staff_user_id
          AND (expected<>'STAFF_REASSIGNED' OR NEW.recipient_user_id IS DISTINCT FROM e.old_assigned_staff_user_id)) THEN
     RAISE EXCEPTION 'Staff notification must concern its affected assignment' USING ERRCODE='23514';
   END IF;
 ELSE RAISE EXCEPTION 'No approved notification for this recipient role' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_notification BEFORE INSERT OR UPDATE OR DELETE ON notifications
 FOR EACH ROW EXECUTE FUNCTION petops_guard_notification();

CREATE FUNCTION petops_create_event_notifications() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE kind text; owner_id uuid; recipient uuid;
BEGIN
 kind:=public.petops_customer_notice_kind(NEW.id);
 IF kind IS NOT NULL THEN
   SELECT c.user_id INTO owner_id FROM public.bookings b JOIN public.customers c ON c.id=b.customer_id WHERE b.id=NEW.booking_id;
   INSERT INTO public.notifications(id,recipient_user_id,recipient_role,booking_id,source_event_id,kind,created_at)
     SELECT gen_random_uuid(),owner_id,'CUSTOMER',NEW.booking_id,NEW.id,kind,clock_timestamp()
     WHERE EXISTS (SELECT 1 FROM public.users WHERE id=owner_id AND role='CUSTOMER' AND is_active)
     ON CONFLICT ON CONSTRAINT uq_notification_event_recipient_kind DO NOTHING;
 END IF;
 kind:=public.petops_staff_notice_kind(NEW.id);
 IF kind IS NOT NULL THEN
   FOR recipient IN SELECT DISTINCT who FROM
       (VALUES (NEW.new_assigned_staff_user_id),(CASE WHEN kind='STAFF_REASSIGNED' THEN NEW.old_assigned_staff_user_id END)) AS affected(who)
       WHERE who IS NOT NULL LOOP
     INSERT INTO public.notifications(id,recipient_user_id,recipient_role,booking_id,source_event_id,kind,created_at)
       SELECT gen_random_uuid(),recipient,'STAFF',NEW.booking_id,NEW.id,kind,clock_timestamp()
       WHERE EXISTS (SELECT 1 FROM public.users WHERE id=recipient AND role='STAFF' AND is_active)
       ON CONFLICT ON CONSTRAINT uq_notification_event_recipient_kind DO NOTHING;
   END LOOP;
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER create_event_notifications AFTER INSERT ON booking_events
 FOR EACH ROW EXECUTE FUNCTION petops_create_event_notifications();

CREATE FUNCTION petops_guard_notification_setting() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='INSERT' AND NEW.id=1 AND NOT NEW.enabled AND NEW.lead_minutes IS NULL
    AND NEW.updated_by_user_id IS NULL AND NEW.updated_at IS NULL
    AND NOT EXISTS (SELECT 1 FROM public.notification_settings) THEN RETURN NEW; END IF;
 IF TG_OP<>'UPDATE' OR NEW.id<>OLD.id OR NEW.updated_at IS NULL OR NEW.updated_at>clock_timestamp()
    OR NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.updated_by_user_id AND role='ADMIN' AND is_active) THEN
   RAISE EXCEPTION 'Only attributed Admin reminder configuration updates are allowed' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_notification_setting BEFORE INSERT OR UPDATE OR DELETE ON notification_settings
 FOR EACH ROW EXECUTE FUNCTION petops_guard_notification_setting();

CREATE FUNCTION petops_guard_management_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Management history is append-only' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.actor_user_id AND role='ADMIN' AND is_active)
    OR (NEW.staff_user_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.users WHERE id=NEW.staff_user_id AND role='STAFF'))
    OR NEW.created_at>clock_timestamp() OR jsonb_typeof(NEW.details::jsonb)<>'object' THEN
   RAISE EXCEPTION 'Management audit requires true Admin and typed target' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER guard_management_event BEFORE INSERT OR UPDATE OR DELETE ON management_events
 FOR EACH ROW EXECUTE FUNCTION petops_guard_management_event();
