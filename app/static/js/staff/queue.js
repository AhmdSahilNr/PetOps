// Staff work classification \u2014 pure functions (no DOM), imported directly by tests/ui_revamp.mjs.
// Uses only data the server already scoped to this Staff member; the server still decides every action.
import { mytDate } from '../core/format.js';

export const TERMINAL = new Set(['COMPLETED', 'CANCELLED', 'REJECTED', 'CHECKED_OUT']);
export const ONGOING = new Set(['IN_PROGRESS', 'CHECKED_IN', 'STAYING']);

export function ownPeriods(b, userId, now = new Date()) {
  return (b.responsibility_periods || []).filter((r) => r.staff_user_id === userId && !r.released_at && new Date(r.effective_end) > now);
}

/** active | today | upcoming | completed */
export function staffSection(b, userId, today = mytDate(), now = new Date()) {
  if (TERMINAL.has(b.status)) return 'completed';
  if (ONGOING.has(b.status) && (b.booking_type === 'GROOMING' || b.current_staff_user_id === userId)) return 'active';
  const own = ownPeriods(b, userId, now);
  if (own.length && own.every((r) => new Date(r.starts_at) > now)) return 'upcoming'; // future handover or later responsibility
  if (ONGOING.has(b.status)) return 'active';
  const day = b.booking_type === 'GROOMING' ? mytDate(b.grooming_start) : b.boarding_start;
  return day <= today ? 'today' : 'upcoming';
}

/** The single next permitted action for this Staff member, or a reason why there is none. */
export function staffNextAction(b, userId, today = mytDate(), now = new Date()) {
  const own = ownPeriods(b, userId, now);
  const futureOnly = own.length && own.every((r) => new Date(r.starts_at) > now);
  if (TERMINAL.has(b.status)) return { action: null, reason: '' }; // QA F-05: finished work needs no ownership message
  if (b.status === 'SUBMITTED') return { action: null, reason: 'Waiting for Admin to confirm' };
  if (b.booking_type === 'GROOMING') {
    // Server rule (17 Nov QA): an unreleased responsibility authorises Grooming actions with no clock cutoff.
    const holds = (b.responsibility_periods || []).some((r) => r.staff_user_id === userId && !r.released_at);
    if (!holds) return { action: null, reason: 'Another team member is responsible' };
    if (b.status === 'CONFIRMED') return { action: 'start', label: 'Start grooming' };
    if (b.status === 'IN_PROGRESS') return { action: 'complete', label: 'Complete grooming' };
    return { action: null, reason: '' };
  }
  if (futureOnly) return { action: null, reason: 'Your responsibility starts later', startsAt: own[0].starts_at };
  {
    const mine = b.current_staff_user_id === userId;
    if (b.status === 'CONFIRMED') {
      if (b.boarding_start > today) return { action: null, reason: 'Arrives later' };
      if (b.boarding_end <= today) return { action: null, reason: 'Stay dates have passed; Admin decides next steps' };
      return mine ? { action: 'check-in', label: 'Check in' } : { action: null, reason: 'Another team member is responsible today' };
    }
    if (ONGOING.has(b.status)) return mine ? { action: 'note', label: 'Add stay update', secondary: { action: 'check-out', label: 'Check out' } }
      : { action: null, reason: 'Another team member is responsible now' };
  }
  return { action: null, reason: '' };
}

/** Sort key: soonest first for open work, newest first for completed. */
export function workStart(b) { return b.grooming_start ? Date.parse(b.grooming_start) : Date.parse(`${b.boarding_start}T00:00:00+08:00`); }
