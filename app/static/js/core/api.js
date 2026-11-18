// Single fetch wrapper. Server errors become ApiError with plain-language copy decided in ONE place.
export class ApiError extends Error {
  constructor(status, detail, message, fields = {}) { super(message); this.status = status; this.detail = detail; this.fields = fields; }
}

const listeners = new Set();
export const onUnauthorized = (fn) => listeners.add(fn);

const FRIENDLY = [
  [/Invalid credentials/i, 'That email and password do not match an active account.'],
  [/Account already exists/i, 'An account with this email already exists. Try signing in instead.'],
  [/No active available Staff/i, 'No groomer is free for the whole appointment at that time. Please choose another time.'],
  [/No configured active accommodation has capacity/i, 'There is no space for those dates. Please try different dates.'],
  [/Grooming start must be in the future/i, 'Choose a time later than now.'],
  [/Boarding start cannot be in the past/i, 'Check-in cannot be in the past.'],
  [/end date must be after start/i, 'Check-out must be after check-in.'],
  [/not Customer-changeable/i, 'This booking can no longer be changed online.'],
  [/eligible Staff assignment and future schedule required/i, 'Assign an available groomer before confirming, and make sure the appointment is still in the future.'],
  [/matching active accommodation allocation required/i, 'Allocate active accommodation for the full stay before confirming.'],
  [/Grooming Staff window is stale/i, 'The groomer assignment no longer matches the appointment. Assign the groomer again, then confirm.'],
  [/allocation is stale or inactive/i, 'The accommodation allocation no longer matches the stay. Allocate again, then confirm.'],
  [/conflicting PetOps work|conflicting PetOps assignments/i, 'This team member already has work at that time. Choose someone else.'],
  [/insufficient capacity/i, 'That accommodation is full for part of the stay. Choose another unit.'],
  [/physically full/i, 'That accommodation is physically full. Check out a departing pet first.'],
  [/Check-in is permitted only within/i, 'Check-in is only possible during the reserved stay dates.'],
  [/Only currently responsible Staff/i, 'Only the team member currently responsible can record this.'],
  [/changed concurrently|Concurrent resource change/i, 'Someone else changed this just now. The latest information has been loaded; please try again.'],
  [/Reassign or finish current\/upcoming work/i, 'This team member still has current or upcoming work. Reassign it before deactivating the account.'],
  [/Configuration would invalidate active allocations/i, 'Pets are already allocated beyond that capacity. Reallocate them first.'],
  [/Effective time must be now or later/i, 'Choose a handover time from now until the end of the stay.'],
  [/Pet with booking history cannot be deleted/i, 'Pets with booking history are archived, not deleted.'],
  [/Admin must configure a lead time/i, 'Enter a reminder lead time before turning reminders on.'],
  [/Active Grooming requires duration/i, 'Active grooming services need a duration.'],
];

export function friendly(status, detail) {
  if (typeof detail === 'string') {
    for (const [re, msg] of FRIENDLY) if (re.test(detail)) return msg;
  }
  if (status === 401) return 'Please sign in to continue.';
  if (status === 403) return 'Your account does not have access to this.';
  if (status === 404) return 'This record is not available to you, or it no longer exists.';
  if (status === 409) return typeof detail === 'string' ? detail.replace(/^BR-\d+:\s*/, '') : 'This change conflicts with the latest records. Reload and try again.';
  if (status === 422) return 'Some details need attention.';
  if (status === 503) return 'PetOps cannot reach its database right now. Try again in a moment.';
  return 'The request could not be completed. Check your connection and try again.';
}

function fieldErrors(detail) {
  const out = {};
  if (Array.isArray(detail)) for (const e of detail) {
    const key = (e.loc || []).filter((p) => p !== 'body').join('.') || '_';
    const msg = String(e.msg || '').replace(/^Value error, /, '');
    out[key] = msg.charAt(0).toUpperCase() + msg.slice(1);
  }
  return out;
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method, signal, credentials: 'same-origin', cache: 'no-store',
      headers: body !== undefined ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError(0, null, 'PetOps could not be reached. Check your connection and try again.');
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    const detail = data && data.detail;
    const err = new ApiError(res.status, detail, friendly(res.status, detail), fieldErrors(detail));
    if (res.status === 401 && path !== '/auth/login') listeners.forEach((fn) => fn(err));
    throw err;
  }
  return data;
}

export const get = (path, opts) => api(path, opts);
export const post = (path, body = {}) => api(path, { method: 'POST', body });
export const put = (path, body = {}) => api(path, { method: 'PUT', body });
export const qs = (params) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : '';
};
