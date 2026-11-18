// Staff agenda \u2014 a read-only view of this Staff member's OWN responsibility periods (FR-018 schedule).
// It is not availability: generic working windows were retired by the approved PS-01 change.
import { h, icon, replace } from '../core/dom.js';
import { href } from '../core/router.js';
import { pageHead, chip, skeleton, errorState, notice } from '../core/ui.js';
import { mytDate, addDays, fmtTime, fmtDayNum, fmtWeekday, fmtShort, daysBetween, nights } from '../core/format.js';
import { loadWork, jobPath } from './work.js';

const DAYS = 14;

export function agendaEntries(bookings, userId, start, days = DAYS, now = new Date()) {
  const out = new Map();
  for (let i = 0; i < days; i += 1) out.set(addDays(start, i), []);
  const end = addDays(start, days);
  for (const b of bookings) {
    if (['COMPLETED', 'CANCELLED', 'REJECTED', 'CHECKED_OUT'].includes(b.status)) continue;
    const periods = (b.responsibility_periods || []).filter((r) => r.staff_user_id === userId && !r.released_at && new Date(r.effective_end) > now);
    for (const r of periods) {
      if (b.booking_type === 'GROOMING') {
        const day = mytDate(r.starts_at);
        if (out.has(day)) out.get(day).push({ b, r, kind: 'grooming', from: r.starts_at, to: r.effective_end });
      } else {
        let day = mytDate(r.starts_at) < start ? start : mytDate(r.starts_at);
        const last = mytDate(new Date(Date.parse(r.effective_end) - 1));
        while (day <= last && day < end) {
          if (out.has(day)) out.get(day).push({ b, r, kind: 'boarding', day, first: day === b.boarding_start, lastDay: addDays(day, 1) === b.boarding_end });
          day = addDays(day, 1);
        }
      }
    }
  }
  for (const list of out.values()) list.sort((x, y) => (x.kind === 'grooming' ? Date.parse(x.from) : 0) - (y.kind === 'grooming' ? Date.parse(y.from) : 0));
  return out;
}

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(6));
  root.append(pageHead({ title: 'Agenda', context: `Next ${DAYS} days, read-only`,
    actions: h('a', { class: 'btn btn--secondary', href: href('/work') }, icon('list'), 'My work') }), host);
  let all;
  try { all = await loadWork(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const today = mytDate();
  const days = agendaEntries(all, ctx.user.id, today);
  replace(host, h('div', { class: 'agenda' }, [...days].map(([day, list]) => h('section', { class: ['agenda-day', day === today && 'is-today', !list.length && 'is-empty'], 'aria-label': `${fmtWeekday(day)} ${fmtShort(day)}` },
    h('div', { class: 'agenda-day__date' }, h('b', {}, fmtDayNum(day)), h('span', {}, `${day === today ? 'Today' : fmtWeekday(day)}, ${fmtShort(day).replace(/^\d+\s/, '')}`)),
    h('div', { class: 'agenda-entries' }, list.length ? list.map((e) => h('a', { class: ['agenda-entry', e.kind === 'boarding' && 'agenda-entry--boarding'], href: href(jobPath(e.b)) },
      h('span', { class: 'agenda-entry__time' }, e.kind === 'grooming' ? `${fmtTime(e.from)}\u2013${fmtTime(e.to)}`
        : e.first ? 'Arrival day' : e.lastDay ? 'Last night' : `Night ${daysBetween(e.b.boarding_start, e.day) + 1} of ${nights(e.b.boarding_start, e.b.boarding_end)}`),
      h('span', {}, h('b', {}, e.b.pet_name), h('span', { class: 'small muted' }, `, ${e.b.service_name}${e.b.accommodation_name ? `, ${e.b.accommodation_name}` : ''}`),
        e.b.status === 'SUBMITTED' ? h('span', { class: 'tag tag--warn', style: { 'margin-left': '8px' } }, 'Not confirmed yet') : null),
      chip(e.b.status))) : h('div', { class: 'agenda-free' }, 'Nothing assigned'))))),
  notice('info', 'About this agenda', 'PetOps assigns work from booking dates. There are no separate shift or availability schedules.'));
}
