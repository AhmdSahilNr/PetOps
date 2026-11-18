// Staff My work \u2014 "What am I supposed to do next?" answered in seconds. Only this Staff member's scoped work.
import { h, icon, replace } from '../core/dom.js';
import { get } from '../core/api.js';
import { href, replaceQuery } from '../core/router.js';
import { pageHead, panel, chip, segmented, kpi, empty, skeleton, errorState, button, updatedStamp, flagTag } from '../core/ui.js';
import { isOverdueStay } from '../core/labels.js';
import { fmtLong, mytDate, fmtTime, fmtDayNum, fmtWeekday, scheduleText, relativeDay, fmtDateTime } from '../core/format.js';
import { staffSection, staffNextAction, workStart } from './queue.js';
import { runAction } from './actions.js';

export async function loadWork() {
  const [g, b] = await Promise.all([get('/grooming/bookings'), get('/boarding/bookings')]);
  return [...g, ...b];
}
export const jobPath = (b) => `/work/${b.booking_type.toLowerCase()}/${b.id}`;

export function workRow(b, userId, after, today = mytDate()) {
  const g = b.booking_type === 'GROOMING';
  const next = staffNextAction(b, userId, today);
  const day = g ? mytDate(b.grooming_start) : b.boarding_start;
  const timeBox = g ? h('div', { class: 'rowitem__time' }, h('b', {}, fmtTime(b.grooming_start).replace(/\s?[ap]m/i, '')), h('span', {}, `${/pm/i.test(fmtTime(b.grooming_start)) ? 'pm' : 'am'}, ${relativeDay(day, today)}`))
    : h('div', { class: 'rowitem__time' }, h('b', {}, fmtDayNum(b.boarding_start)), h('span', {}, `${fmtWeekday(b.boarding_start)}, check-in`));
  const later = staffSection(b, userId, today) === 'upcoming'; // QA F-15: allowed, but not visually primary before the day
  const primary = next.action ? button(later && g ? `${next.label} (${relativeDay(day, today)})` : next.label, { size: 'sm', variant: later ? 'secondary' : '', icon: { start: 'play', complete: 'check', 'check-in': 'door_in', note: 'note' }[next.action],
    onClick: (e) => runAction(next.action, b, e.currentTarget, after) }) : null;
  const secondary = next.secondary ? button(next.secondary.label, { size: 'sm', variant: 'secondary', icon: 'door_out', onClick: (e) => runAction(next.secondary.action, b, e.currentTarget, after) }) : null;
  return h('div', { class: ['rowitem', 'work-row', b.status === 'IN_PROGRESS' || b.status === 'STAYING' ? 'work-row--now' : null] }, timeBox,
    h('div', { class: 'rowitem__main' },
      h('div', { class: 'rowitem__title' }, h('a', { href: href(jobPath(b)) }, b.pet_name), chip(b.status), isOverdueStay(b, today) ? flagTag('past_planned_checkout') : null),
      h('div', { class: 'rowitem__meta' }, h('span', {}, icon(g ? 'scissors' : 'bed'), b.service_name), h('span', {}, scheduleText(b)),
        !g && b.accommodation_name ? h('span', {}, icon('home_care'), b.accommodation_name) : null, h('span', {}, icon('user'), b.customer_name)),
      !next.action && next.reason ? h('span', { class: 'action-hint' }, next.startsAt ? `${next.reason} (${fmtDateTime(next.startsAt)})` : next.reason) : null),
    h('div', { class: 'rowitem__side' }, primary, secondary, h('a', { class: 'btn btn--ghost btn--sm', href: href(jobPath(b)), 'aria-label': `Open ${b.pet_name}` }, 'Open')));
}

export async function render(root, ctx) {
  const me = ctx.user.id;
  let filter = ['GROOMING', 'BOARDING'].includes(ctx.query.type) ? ctx.query.type : 'ALL';
  const host = h('div', {}, skeleton(6));
  const stamp = updatedStamp(() => ctx.refresh());
  root.append(pageHead({ title: 'My work', context: [h('span', {}, fmtLong(mytDate())), stamp.el] }), host);
  let all;
  try { all = await loadWork(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const today = mytDate();
  const draw = () => {
    const list = all.filter((b) => filter === 'ALL' || b.booking_type === filter);
    const by = { active: [], today: [], upcoming: [], completed: [] };
    for (const b of list) by[staffSection(b, me, today)].push(b);
    by.active.sort((a, b) => workStart(a) - workStart(b)); by.today.sort((a, b) => workStart(a) - workStart(b));
    by.upcoming.sort((a, b) => workStart(a) - workStart(b)); by.completed.sort((a, b) => workStart(b) - workStart(a));
    const after = () => ctx.refresh();
    const section = (key, title, ic, emptyTitle, emptyText) => panel({ title, icon: ic, count: by[key].length, flush: true, className: 'work-section', id: `sec-${key}`,
      body: by[key].length ? h('div', { class: 'rows' }, (key === 'completed' ? by[key].slice(0, 8) : by[key]).map((b) => workRow(b, me, after, today)))
        : empty({ icon: ic, title: emptyTitle, text: emptyText, compact: true }),
      foot: key === 'completed' && by.completed.length > 8 ? h('a', { href: href('/history') }, 'See all completed work') : null });
    const jump = (key) => () => { const el = document.getElementById(`sec-${key}`); if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'start' }); el.querySelector('h2')?.focus?.(); } };
    replace(host,
      h('div', { class: 'summary-strip' },
        kpi({ label: 'In progress now', icon: 'home_care', value: by.active.length, meaning: 'Grooming started or pets staying', onClick: jump('active'), alert: by.active.length > 0 }),
        kpi({ label: 'Today', icon: 'sun', value: by.today.length, meaning: 'Appointments and arrivals', onClick: jump('today') }),
        kpi({ label: 'Upcoming', icon: 'calendar', value: by.upcoming.length, meaning: 'Assigned for later dates', onClick: jump('upcoming') }),
        kpi({ label: 'Completed', icon: 'check_circle', value: by.completed.length, meaning: 'Finished work you handled', onClick: jump('completed') })),
      h('div', { class: 'row row--wrap row--between', style: { 'margin-bottom': '16px' } },
        segmented([{ value: 'ALL', label: 'All work' }, { value: 'GROOMING', label: 'Grooming', icon: 'scissors' }, { value: 'BOARDING', label: 'Boarding', icon: 'bed' }],
          filter, (v) => { filter = v; replaceQuery(v === 'ALL' ? {} : { type: v }); draw(); }, 'Service'),
        h('a', { class: 'btn btn--secondary btn--sm', href: href('/agenda') }, icon('agenda'), 'Open agenda')),
      h('div', { class: 'stack' },
        section('active', 'Needs you now', 'home_care', 'Nothing in progress', 'No grooming has started and no pets are staying under your care right now.'),
        section('today', 'Today', 'sun', 'Nothing else today', 'You have no more appointments or arrivals assigned for today.'),
        section('upcoming', 'Upcoming', 'calendar', 'No upcoming work', 'New assignments from Admin will appear here and in Notifications.'),
        section('completed', 'Recently completed', 'check_circle', 'No completed work yet', 'Work you finish is kept here and in History.')));
  };
  draw();
}
