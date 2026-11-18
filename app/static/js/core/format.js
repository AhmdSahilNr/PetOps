// Business time is Malaysia time (MYT, Asia/Kuala_Lumpur, UTC+8, no daylight saving). Pure functions: no DOM.
export const TZ = 'Asia/Kuala_Lumpur';
const OFFSET = '+08:00';
const fmt = (opts) => new Intl.DateTimeFormat('en-MY', { timeZone: TZ, ...opts });
const F = {
  day: fmt({ weekday: 'short', day: 'numeric', month: 'short' }),
  dayYear: fmt({ weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }),
  date: fmt({ day: 'numeric', month: 'short', year: 'numeric' }),
  short: fmt({ day: 'numeric', month: 'short' }),
  time: fmt({ hour: 'numeric', minute: '2-digit', hour12: true }),
  weekday: fmt({ weekday: 'short' }),
  dayNum: fmt({ day: 'numeric' }),
  long: fmt({ weekday: 'long', day: 'numeric', month: 'long' }),
};

/** YYYY-MM-DD for "today" in MYT from a clock instant (defaults to now). */
export function mytDate(instant = new Date()) {
  const d = new Date(instant);
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  return parts; // en-CA gives YYYY-MM-DD
}
/** A calendar date string (YYYY-MM-DD) as the UTC instant of MYT midnight. */
export function dateToInstant(dateStr) { return new Date(`${dateStr}T00:00:00${OFFSET}`); }
export function addDays(dateStr, n) {
  const d = new Date(`${dateStr}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10);
}
export function daysBetween(a, b) { return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000); }
/** Local MYT date + HH:MM to an ISO instant with explicit +08:00 offset (what the API expects). */
export function mytInstant(dateStr, timeStr) { return `${dateStr}T${timeStr}:00${OFFSET}`; }
export function mytTimeOf(iso) { return new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(iso)); }

const asDate = (v) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? dateToInstant(v) : new Date(v));
export const fmtDay = (v) => F.day.format(asDate(v));
export const fmtDayYear = (v) => F.dayYear.format(asDate(v));
export const fmtDate = (v) => F.date.format(asDate(v));
export const fmtShort = (v) => F.short.format(asDate(v));
export const fmtTime = (v) => F.time.format(new Date(v)).replace(' ', '\u00a0');
export const fmtWeekday = (v) => F.weekday.format(asDate(v));
export const fmtDayNum = (v) => F.dayNum.format(asDate(v));
export const fmtLong = (v) => F.long.format(asDate(v));
export const fmtDateTime = (v) => `${fmtDay(v)}, ${fmtTime(v)}`;
export function fmtStamp(iso) { return iso ? `${fmtDate(iso)}, ${fmtTime(iso)}` : ''; }

export function nights(start, end) { return Math.max(0, daysBetween(start, end)); }
export function plural(n, one, many = `${one}s`) { return `${n} ${n === 1 ? one : many}`; }

/** Short relative label for a calendar date compared with today (MYT). */
export function relativeDay(dateStr, today = mytDate()) {
  const d = daysBetween(today, dateStr);
  if (d === 0) return 'Today';
  if (d === 1) return 'Tomorrow';
  if (d === -1) return 'Yesterday';
  if (d > 1 && d < 7) return fmtWeekday(dateStr);
  return fmtShort(dateStr);
}

/** Start instant (Date) of a booking; Boarding starts at MYT midnight of its check-in date. */
export function bookingStart(b) { return b.grooming_start ? new Date(b.grooming_start) : dateToInstant(b.boarding_start); }
export function bookingDate(b) { return b.grooming_start ? mytDate(b.grooming_start) : b.boarding_start; }

/** Human schedule line for any booking. */
export function scheduleText(b) {
  if (b.booking_type === 'GROOMING' || b.grooming_start) {
    const end = b.grooming_duration_minutes ? new Date(Date.parse(b.grooming_start) + b.grooming_duration_minutes * 60000) : null;
    return `${fmtDay(b.grooming_start)}, ${fmtTime(b.grooming_start)}${end ? `\u2013${fmtTime(end)}` : ''}`;
  }
  return `${fmtDay(b.boarding_start)} to ${fmtDay(b.boarding_end)} (${plural(nights(b.boarding_start, b.boarding_end), 'night')})`;
}
export function scheduleFromSnapshot(s) {
  if (!s) return '';
  if (s.grooming_start) return `${fmtDay(s.grooming_start)}, ${fmtTime(s.grooming_start)}`;
  if (s.boarding_start) return `${fmtDay(s.boarding_start)} to ${fmtDay(s.boarding_end)}`;
  return '';
}

export function minutesText(m) {
  if (!m) return '';
  const h = Math.floor(m / 60), r = m % 60;
  return h ? `${h} hr${r ? ` ${r} min` : ''}` : `${r} min`;
}

/** Percentage change shown only when the previous value is at least 10; never NaN or Infinity. */
export function changeVersus(current, previous) {
  if (previous === null || previous === undefined || current === null || current === undefined) return null;
  const diff = current - previous;
  if (previous >= 10) return { diff, pct: Math.round((diff / previous) * 100) };
  return { diff, pct: null };
}

export function initials(name) {
  const parts = String(name || '?').trim().split(/\s+/).filter(Boolean);
  return ((parts[0] || '?')[0] + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

export function greeting(now = new Date()) {
  const hour = Number(new Intl.DateTimeFormat('en-GB', { timeZone: TZ, hour: '2-digit', hour12: false }).format(now));
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
}
