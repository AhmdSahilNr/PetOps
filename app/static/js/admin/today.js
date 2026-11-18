// Admin Today \u2014 the operations centre. Every count is len(list) of a server-defined list and opens that same list.
import { h, icon, replace } from '../core/dom.js';
import { get } from '../core/api.js';
import { href } from '../core/router.js';
import { pageHead, panel, kpi, empty, skeleton, errorState, pips, meter, updatedStamp, avatar } from '../core/ui.js';
import { fmtLong, fmtDayNum, fmtWeekday, fmtShort, relativeDay, mytDate, plural } from '../core/format.js';
import { opRow, drillDown } from './common.js';

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(8));
  const stamp = updatedStamp(() => ctx.refresh());
  root.append(pageHead({ title: 'Today', context: [h('span', {}, fmtLong(mytDate())), stamp.el],
    actions: [h('a', { class: 'btn btn--secondary', href: href('/boarding') }, icon('board'), 'Lodging board'), h('a', { class: 'btn', href: href('/bookings', { view: 'decision' }) }, icon('list'), 'Review requests')] }), host);
  let o;
  try { o = await get('/admin/operations'); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const D = o.definitions;
  const ready = o.needs_decision.filter((b) => b.flags.includes('ready')).length;
  const blocked = o.needs_decision.length - ready;
  const cap = o.capacity_now;
  const lane = (title, ic, list, emptyText) => [h('div', { class: 'lane-title' }, icon(ic), `${title} (${list.length})`),
    list.length ? list.map((b) => opRow(b)) : h('div', { class: 'lane-empty' }, emptyText)];
  const byDay = new Map();
  for (const b of o.coming_up) { const d = b.grooming_start ? mytDate(b.grooming_start) : b.boarding_start; if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push(b); }
  const maxWork = Math.max(1, ...o.staff_work.map((s) => s.now.length + s.next_7_days.length));

  replace(host,
    h('section', { class: 'attention', 'aria-label': 'Needs attention' },
      kpi({ label: 'Needs decision', icon: 'clock', value: o.needs_decision.length, alert: o.needs_decision.length > 0,
        meaning: o.needs_decision.length ? `${ready} ready to confirm, ${blocked} need preparation` : 'No booking decisions waiting',
        onClick: () => drillDown('Needs decision', o.needs_decision, D.needs_decision) }),
      kpi({ label: 'Grooming today', icon: 'scissors', value: o.grooming_today.length, meaning: `${o.grooming_today.filter((b) => b.status === 'COMPLETED').length} completed so far`,
        onClick: () => drillDown('Grooming today', o.grooming_today, D.grooming_today) }),
      kpi({ label: 'Arrivals today', icon: 'door_in', value: o.arrivals_today.length, meaning: 'Confirmed stays starting today',
        onClick: () => drillDown('Arrivals today', o.arrivals_today, D.arrivals_today) }),
      kpi({ label: 'Departures due', icon: 'door_out', value: o.departures_due.length, alert: o.departures_due.some((b) => b.flags.includes('past_planned_checkout')),
        meaning: 'Staying pets due to check out today or earlier', onClick: () => drillDown('Departures due', o.departures_due, D.departures_due) }),
      kpi({ label: 'In care now', icon: 'home_care', value: o.in_care.length, unit: `of ${cap.capacity} places`, meaning: `${cap.available} places free right now`, // QA F-14: tile = list
        onClick: () => drillDown('In care now', o.in_care, D.in_care) })),
    h('div', { class: 'today-grid' },
      h('div', { class: 'stack' },
        panel({ title: 'Needs decision', icon: 'clock', count: o.needs_decision.length, flush: true,
          actions: h('a', { class: 'small', href: href('/bookings', { view: 'decision' }) }, 'Open queue'),
          body: o.needs_decision.length ? h('div', { class: 'rows' }, o.needs_decision.slice(0, 6).map((b) => opRow(b)))
            : empty({ icon: 'check_circle', title: 'No booking decisions need attention', text: 'New requests and changed bookings will appear here.', compact: true }) }),
        panel({ title: 'Today\u2019s schedule', icon: 'sun', flush: true, body: h('div', {},
          lane('Grooming', 'scissors', o.grooming_today, 'No grooming is booked for today.'),
          lane('Arrivals', 'door_in', o.arrivals_today, 'No arrivals expected today.'),
          lane('Departures due', 'door_out', o.departures_due, 'No departures due today.')) }),
        panel({ title: 'Coming up', icon: 'calendar', count: o.coming_up.length, flush: true,
          actions: h('span', { class: 'small muted' }, `${fmtShort(o.coming_up_range.from_date)} to ${fmtShort(o.coming_up_range.to_date)}`),
          body: o.coming_up.length ? h('div', {}, [...byDay].map(([day, list]) => h('div', { class: 'daygroup' },
            h('div', { class: 'daygroup__date' }, h('b', {}, fmtDayNum(day)), h('span', {}, relativeDay(day) === 'Tomorrow' ? 'Tomorrow' : fmtWeekday(day))),
            h('div', { class: 'rows' }, list.map((b) => opRow(b, { showDate: false }))))))
            : empty({ icon: 'calendar', title: 'Nothing confirmed for the next 7 days', compact: true }) })),
      h('div', { class: 'stack' },
        panel({ title: 'Boarding now', icon: 'board', actions: h('a', { class: 'small', href: href('/boarding') }, 'Lodging board'),
          body: h('div', {}, cap.units.filter((u) => u.is_active).map((u) => h('div', { class: 'unit-line' },
            h('div', {}, h('b', {}, u.name), h('div', { class: 'sub' }, `${u.category}, ${plural(u.available, 'place')} free`)),
            pips(u.capacity, u.occupied, u.occupied, { label: `${u.name}: ${u.occupied} of ${u.capacity} places in use` }))),
          !cap.units.some((u) => u.is_active) ? empty({ icon: 'bed', title: 'No accommodation set up', text: 'Add units in Settings, Boarding setup.', compact: true }) : null) }),
        panel({ title: 'Staff work', icon: 'users', actions: h('a', { class: 'small', href: href('/staff-work') }, 'Details'),
          body: o.staff_work.length ? h('div', {}, o.staff_work.map((s) => h('div', { class: 'staff-line' }, avatar(s.name, 'avatar--sm avatar--staff'),
            h('div', {}, h('b', {}, s.name), h('div', { class: 'small muted' }, `${s.now.length} now, ${s.next_7_days.length} in the next 7 days`), meter(s.now.length + s.next_7_days.length, maxWork)),
            h('span', { class: 'num strong' }, String(s.now.length + s.next_7_days.length)))))
            : empty({ icon: 'users', title: 'No active team members', compact: true }) }),
        h('details', { class: 'panel panel__body small' }, h('summary', { class: 'strong' }, 'How these numbers are counted'),
          h('dl', { class: 'stack stack--sm', style: { 'margin-top': '12px' } }, Object.entries(D).map(([k, v]) => h('div', {},
            h('dt', { class: 'strong' }, k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())), h('dd', { class: 'muted' }, v))))))));
}
