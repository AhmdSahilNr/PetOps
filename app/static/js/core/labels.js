// ONE vocabulary for every role (directive 03 \u00a722). Pure module: no DOM, importable by node tests.
import { fmtDay, fmtTime, fmtDate, nights, plural } from './format.js';

export const STATUS = {
  SUBMITTED:   { label: 'Requested',   tone: 'requested',   icon: 'clock' },
  CONFIRMED:   { label: 'Confirmed',   tone: 'confirmed',   icon: 'check' },
  IN_PROGRESS: { label: 'In progress', tone: 'in-progress', icon: 'scissors' },
  CHECKED_IN:  { label: 'Staying',     tone: 'checked-in',  icon: 'bed' },     // legacy arrival record (PS addendum: shown as Staying)
  STAYING:     { label: 'Staying',     tone: 'staying',     icon: 'bed' },
  CHECKED_OUT: { label: 'Checked out', tone: 'checked-out', icon: 'door_out' }, // legacy: completion pending
  COMPLETED:   { label: 'Completed',   tone: 'completed',   icon: 'check_circle' },
  REJECTED:    { label: 'Rejected',    tone: 'rejected',    icon: 'x_circle' },
  CANCELLED:   { label: 'Cancelled',   tone: 'cancelled',   icon: 'ban' },
};
export const statusLabel = (s) => (STATUS[s] || { label: 'Updated' }).label;

export const SERVICE = {
  GROOMING: { label: 'Grooming', icon: 'scissors' },
  BOARDING: { label: 'Boarding', icon: 'bed' },
};

export const CHANGEABLE = new Set(['SUBMITTED', 'CONFIRMED']);       // FR-009 / BR: Customer and Admin pre-work changes
export const IN_CARE = new Set(['IN_PROGRESS', 'CHECKED_IN', 'STAYING']);
export const FINISHED = new Set(['COMPLETED', 'CHECKED_OUT']);
export const CLOSED = new Set(['REJECTED', 'CANCELLED']);

/** Customer booking groups for My Bookings. */
export function customerGroup(b) {
  if (CLOSED.has(b.status)) return 'closed';
  if (FINISHED.has(b.status)) return 'past';
  if (IN_CARE.has(b.status)) return 'in_care';
  return 'upcoming';
}

/** "What happens next" for the Customer \u2014 derived only from implemented statuses (no new rules). */
export function customerNextStep(b, petName = 'your pet') {
  const g = b.booking_type === 'GROOMING';
  switch (b.status) {
    case 'SUBMITTED':
      return { title: 'Waiting for PetOps to confirm', text: g
        ? 'We check that a groomer is free for the whole appointment, then confirm or let you know. Your time is held only after confirmation.'
        : 'We reserve a place for the whole stay, then confirm or let you know. The place is held only after confirmation.' };
    case 'CONFIRMED':
      return g
        ? { title: `See you ${fmtDay(b.grooming_start)} at ${fmtTime(b.grooming_start)}`, text: 'Your appointment is confirmed. You can still change or cancel it before grooming starts.' }
        : { title: `Check-in from ${fmtDay(b.boarding_start)}`, text: `Your ${plural(nights(b.boarding_start, b.boarding_end), 'night')} stay is confirmed. You can still change or cancel it before check-in.` };
    case 'IN_PROGRESS':
      return { title: `${petName} is being groomed`, text: 'Grooming has started. Changes are no longer possible online.' };
    case 'STAYING':
    case 'CHECKED_IN':
      return { title: `${petName} is staying with us`, text: `Planned check-out ${fmtDay(b.boarding_end)}. Stay updates from the team appear below.` };
    case 'CHECKED_OUT':
      return { title: 'Checked out', text: 'Departure is recorded; final completion is still pending on this older record.' };
    case 'COMPLETED':
      return { title: 'Completed', text: g ? 'Grooming is finished. Notes from the groomer are below.' : 'The stay is finished. Stay updates remain available below.' };
    case 'REJECTED':
      return { title: 'This request could not be accepted', text: 'PetOps could not accept this request. You can book another time.' };
    case 'CANCELLED':
      return { title: 'Cancelled', text: 'This booking was cancelled. Its history stays available here.' };
    default:
      return { title: statusLabel(b.status), text: '' };
  }
}

/** Lifecycle steps for the status tracker (only implemented statuses). */
export function trackerSteps(b) {
  const g = b.booking_type === 'GROOMING';
  const flow = g ? ['SUBMITTED', 'CONFIRMED', 'IN_PROGRESS', 'COMPLETED'] : ['SUBMITTED', 'CONFIRMED', 'STAYING', 'COMPLETED'];
  const labels = g ? ['Requested', 'Confirmed', 'In progress', 'Completed'] : ['Requested', 'Confirmed', 'Staying', 'Completed'];
  const icons = g ? ['clock', 'check', 'scissors', 'check_circle'] : ['clock', 'check', 'bed', 'check_circle'];
  const status = b.status === 'CHECKED_IN' ? 'STAYING' : b.status === 'CHECKED_OUT' ? 'STAYING' : b.status;
  if (CLOSED.has(status)) {
    return [{ label: 'Requested', icon: 'clock', state: 'done' }, { label: statusLabel(status), icon: STATUS[status].icon, state: 'stopped' }];
  }
  const idx = flow.indexOf(status);
  return flow.map((s, i) => ({ label: labels[i], icon: icons[i], state: i < idx || (i === idx && s === 'COMPLETED') ? 'done' : i === idx ? 'current' : 'todo' }));
}

/** Booking events in plain words (used where a server timeline title is not available). */
export const EVENT = {
  BOOKING_SUBMITTED: 'Booking requested', STATUS_CHANGED: 'Status updated', BOOKING_RESCHEDULED: 'Dates changed',
  BOOKING_CANCELLED: 'Booking cancelled', STAFF_ASSIGNED: 'Staff assigned', STAFF_UNASSIGNED: 'Staff assignment removed',
  ACCOMMODATION_ALLOCATED: 'Accommodation allocated', ACCOMMODATION_REALLOCATED: 'Accommodation reallocated',
  GROOMING_STARTED: 'Grooming started', GROOMING_COMPLETED: 'Grooming completed', BOARDING_CHECKED_IN: 'Checked in',
  BOARDING_STAY_STARTED: 'Stay started', BOARDING_STAY_UPDATED: 'Stay update', BOARDING_CHECKED_OUT: 'Checked out',
  BOARDING_COMPLETED: 'Stay completed',
};

/** Readiness flags from the operations centre, in plain words. */
export const FLAG = {
  needs_staff: { label: 'Needs groomer', tone: 'warn', icon: 'user' },
  needs_accommodation: { label: 'Needs accommodation', tone: 'warn', icon: 'bed' },
  ready: { label: 'Ready to confirm', tone: 'ok', icon: 'check' },
  date_passed: { label: 'Date passed', tone: 'danger', icon: 'alert' },
  changed: { label: 'Changed request', tone: 'info', icon: 'swap' },
  start_passed: { label: 'Start time passed', tone: 'warn', icon: 'clock' },
  past_planned_checkout: { label: 'Overdue stay', hint: 'Expected departure passed; the pet has not been checked out', tone: 'danger', icon: 'alert' },
  in_care: { label: 'In care', tone: 'ok', icon: 'home_care' },
};

/**
 * Overdue stay: a derived, display-only exception (no fee, no automatic change). The planned check-out date has
 * passed (MYT) while the stay is still open. Departure today is not overdue; checked-out, completed, cancelled and
 * rejected bookings never are. Mirrors app/operations.py is_overdue_stay.
 */
export function isOverdueStay(b, today) {
  return b.booking_type === 'BOARDING' && (b.status === 'STAYING' || b.status === 'CHECKED_IN') && !!b.boarding_end && b.boarding_end < today;
}

export function serviceLine(b) { return `${b.service_name || SERVICE[b.booking_type]?.label || ''}`; }
export function dateLabelForList(b) { return b.grooming_start ? fmtDate(b.grooming_start) : fmtDate(b.boarding_start); }
