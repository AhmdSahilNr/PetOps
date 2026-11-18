// Pure request builders for Admin preparation actions (imported by tests/ui_revamp.mjs).
// Assignment timing is always derived by the server from the booking; the client never sends duty windows.
const ACTIVE_STAY = new Set(['STAYING', 'CHECKED_IN']);

export function staffAssignmentPayload(booking, staffId, effectiveAtIso = null) {
  if (booking.booking_type === 'BOARDING' && ACTIVE_STAY.has(booking.status)) {
    if (!staffId) throw new Error('Choose the next responsible team member for an active stay');
    return { staff_user_id: staffId, effective_at: effectiveAtIso || new Date().toISOString() };
  }
  return { staff_user_id: staffId || null };
}

export function allocationPayload(accommodationId) { return { accommodation_id: accommodationId }; }
export function decisionPayload(confirm) { return { status: confirm ? 'CONFIRMED' : 'REJECTED' }; }
export function reschedulePayload(type, values) {
  return type === 'GROOMING' ? { grooming_start: values.grooming_start } : { boarding_start: values.boarding_start, boarding_end: values.boarding_end };
}
