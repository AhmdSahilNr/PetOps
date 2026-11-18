// Admin Bookings \u2014 one queue for both services with quick views, search and filters. Filters reset on each visit
// (only the quick view travels in the URL), so a drill-down can never silently hide records later.
import { h, icon, replace } from '../core/dom.js';
import { get } from '../core/api.js';
import { replaceQuery } from '../core/router.js';
import { pageHead, segmented, select, input, empty, skeleton, errorState, updatedStamp } from '../core/ui.js';
import { mytDate, bookingDate, bookingStart } from '../core/format.js';
import { bookingTable } from './common.js';

const VIEWS = [
  ['decision', 'Needs decision'], ['today', 'Today'], ['upcoming', 'Upcoming'], ['care', 'In care'], ['past', 'Completed'], ['closed', 'Cancelled and rejected'], ['all', 'All'],
];

export async function render(root, ctx) {
  let view = VIEWS.some(([k]) => k === ctx.query.view) ? ctx.query.view : 'decision';
  const state = { q: '', type: '', staff: '', sort: 'soonest', from: '', to: '' };
  const host = h('div', {}, skeleton(8));
  const stamp = updatedStamp(() => ctx.refresh());
  root.append(pageHead({ title: 'Bookings', context: stamp.el }), host);
  let ops, rows;
  try {
    const [o, g, b] = await Promise.all([get('/admin/operations'), get('/grooming/bookings'), get('/boarding/bookings')]);
    ops = o; rows = [...g, ...b];
  } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const flags = new Map();
  for (const key of ['needs_decision', 'grooming_today', 'arrivals_today', 'departures_due', 'in_care']) for (const r of ops[key]) flags.set(r.id, [...new Set([...(flags.get(r.id) || []), ...r.flags])]);
  rows = rows.map((r) => ({ ...r, flags: flags.get(r.id) || [] }));
  const today = mytDate();
  const ids = (list) => new Set(list.map((r) => r.id));
  const todayIds = ids([...ops.grooming_today, ...ops.arrivals_today, ...ops.departures_due]);
  const decisionIds = ids(ops.needs_decision);
  const inView = {
    decision: (r) => decisionIds.has(r.id),
    today: (r) => todayIds.has(r.id),
    upcoming: (r) => r.status === 'CONFIRMED' && bookingDate(r) >= today,
    care: (r) => ['IN_PROGRESS', 'STAYING', 'CHECKED_IN'].includes(r.status),
    past: (r) => ['COMPLETED', 'CHECKED_OUT'].includes(r.status),
    closed: (r) => ['REJECTED', 'CANCELLED'].includes(r.status),
    all: () => true,
  };
  const staffNames = [...new Set(rows.map((r) => r.assigned_staff_name).filter(Boolean))].sort();
  const search = input({ type: 'search', placeholder: 'Pet, owner or service', 'aria-label': 'Search bookings', value: '' });
  const typeSel = select([{ value: '', label: 'All services' }, { value: 'GROOMING', label: 'Grooming' }, { value: 'BOARDING', label: 'Boarding' }], { 'aria-label': 'Service' });
  const staffSel = select([{ value: '', label: 'Any team member' }, { value: '__none', label: 'No team member' }, ...staffNames.map((n) => ({ value: n, label: n }))], { 'aria-label': 'Team member' });
  const sortSel = select([{ value: 'soonest', label: 'Service date, soonest first' }, { value: 'latest', label: 'Service date, latest first' }, { value: 'created', label: 'Newest requests first' }], { 'aria-label': 'Sort' });
  const segHost = h('div'); const listHost = h('div');
  const draw = () => {
    const counts = Object.fromEntries(VIEWS.map(([k]) => [k, rows.filter(inView[k]).length]));
    replace(segHost, segmented(VIEWS.map(([value, label]) => ({ value, label, count: counts[value] })), view, (v) => { view = v; replaceQuery({ view: v }); draw(); }, 'Quick views'));
    const term = state.q.trim().toLowerCase();
    let list = rows.filter(inView[view])
      .filter((r) => !state.type || r.booking_type === state.type)
      .filter((r) => !state.staff || (state.staff === '__none' ? !r.assigned_staff_name : r.assigned_staff_name === state.staff))
      .filter((r) => !term || [r.pet_name, r.customer_name, r.service_name].some((v) => (v || '').toLowerCase().includes(term)))
      .filter((r) => (!state.from || bookingDate(r) >= state.from) && (!state.to || bookingDate(r) <= state.to)); // QA F-08: service date range
    list = list.sort(state.sort === 'created' ? (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)
      : state.sort === 'latest' ? (a, b) => bookingStart(b) - bookingStart(a) : (a, b) => bookingStart(a) - bookingStart(b));
    if (view === 'decision' && state.sort === 'soonest') list = ops.needs_decision.map((o) => list.find((r) => r.id === o.id)).filter(Boolean); // oldest request first
    const filtered = state.q || state.type || state.staff || state.from || state.to;
    replace(listHost, h('section', { class: 'panel' }, list.length ? bookingTable(list, { caption: 'Bookings' })
      : empty({ icon: view === 'decision' ? 'check_circle' : 'list', title: filtered ? 'No bookings match these filters' : view === 'decision' ? 'No booking decisions need attention' : 'Nothing in this view',
        text: filtered ? 'Clear the search or filters to see more.' : view === 'decision' ? 'New and changed requests will appear here.' : '' })),
    h('p', { class: 'small muted', style: { 'margin-top': '8px' } }, `${list.length} of ${counts[view]} in this view.`));
  };
  search.addEventListener('input', () => { state.q = search.value; draw(); });
  typeSel.addEventListener('change', () => { state.type = typeSel.value; draw(); });
  staffSel.addEventListener('change', () => { state.staff = staffSel.value; draw(); });
  sortSel.addEventListener('change', () => { state.sort = sortSel.value; draw(); });
  const fromIn = input({ type: 'date', 'aria-label': 'Service date from' }); const toIn = input({ type: 'date', 'aria-label': 'Service date to' });
  fromIn.addEventListener('change', () => { state.from = fromIn.value; draw(); }); toIn.addEventListener('change', () => { state.to = toIn.value; draw(); });
  replace(host, h('div', { style: { 'margin-bottom': '16px' } }, segHost),
    h('div', { class: 'filters' }, h('div', { class: 'field field--grow search' }, icon('search'), search), h('div', { class: 'field' }, typeSel), h('div', { class: 'field' }, staffSel),
      h('div', { class: 'field' }, h('span', { class: 'label small' }, 'Service date from'), fromIn), h('div', { class: 'field' }, h('span', { class: 'label small' }, 'to'), toIn), h('div', { class: 'field' }, sortSel)),
    listHost);
  draw();
}
