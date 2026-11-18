// Customer data access: always fresh from role-scoped endpoints (server returns only this Customer's records).
import { get } from '../core/api.js';
import { bookingStart } from '../core/format.js';
import { CLOSED, FINISHED, IN_CARE } from '../core/labels.js';

export async function loadCustomer({ notifications = false } = {}) {
  const [pets, grooming, boarding, notes] = await Promise.all([
    get('/pets'), get('/grooming/bookings'), get('/boarding/bookings'), notifications ? get('/notifications?limit=6') : null]);
  const bookings = [...grooming, ...boarding].sort((a, b) => bookingStart(a) - bookingStart(b));
  return { pets, bookings, notifications: notes };
}

export const upcoming = (list) => list.filter((b) => b.status === 'SUBMITTED' || b.status === 'CONFIRMED');
export const inCare = (list) => list.filter((b) => IN_CARE.has(b.status));
export const finished = (list) => list.filter((b) => FINISHED.has(b.status)).sort((a, b) => bookingStart(b) - bookingStart(a));
export const closed = (list) => list.filter((b) => CLOSED.has(b.status)).sort((a, b) => bookingStart(b) - bookingStart(a));

/** The one booking the Customer most needs to see now: in care first, then the next confirmed, then the next request. */
export function spotlight(list) {
  return inCare(list)[0]
    || list.find((b) => b.status === 'CONFIRMED' && bookingStart(b) >= startOfToday())
    || list.find((b) => b.status === 'SUBMITTED') || null;
}
function startOfToday() { const d = new Date(); d.setHours(0, 0, 0, 0); return d; }

export function petSummary(pet, list) {
  const mine = list.filter((b) => b.pet_id === pet.id);
  const next = mine.find((b) => (b.status === 'CONFIRMED' || b.status === 'SUBMITTED' || IN_CARE.has(b.status)));
  const last = finished(mine)[0] || null;
  return { bookings: mine, next, last, count: mine.length };
}

export const detailPath = (b) => `/bookings/${b.booking_type.toLowerCase()}/${b.id}`;
