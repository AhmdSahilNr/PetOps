// Admin presentation helpers shared by Today, Bookings, Boarding, History and Insights drill-downs.
import { h, icon } from '../core/dom.js';
import { href } from '../core/router.js';
import { chip, flagTag, avatar, drawer, empty } from '../core/ui.js';
import { scheduleText, fmtTime, mytDate, relativeDay, fmtDayNum, fmtWeekday } from '../core/format.js';

export const workspacePath = (b) => `/bookings/${b.booking_type.toLowerCase()}/${b.id}`;

export function adminNext(b) {
  const flags = b.flags || [];
  if (b.status === 'SUBMITTED') return flags.includes('date_passed') ? 'Reject or reschedule' : flags.includes('needs_staff') ? 'Assign a groomer' : flags.includes('needs_accommodation') ? 'Allocate a place' : 'Review request';
  if (b.status === 'CONFIRMED') return b.booking_type === 'GROOMING' ? 'Groomer starts on the day' : 'Check in on arrival';
  if (b.status === 'IN_PROGRESS') return 'Being groomed';
  if (b.status === 'STAYING' || b.status === 'CHECKED_IN') return flags.includes('past_planned_checkout') ? 'Check out (overdue stay)' : 'In care';
  return '';
}

/** Compact operational row used in lists and drill-downs. */
export function opRow(b, { showDate = true, actions } = {}) {
  const g = b.booking_type === 'GROOMING';
  const day = g ? mytDate(b.grooming_start) : b.boarding_start;
  return h('div', { class: 'rowitem' },
    showDate ? (g ? h('div', { class: 'rowitem__time' }, h('b', {}, fmtTime(b.grooming_start).replace(/\s?[ap]m/i, '')), h('span', {}, `${/pm/i.test(fmtTime(b.grooming_start)) ? 'pm' : 'am'}, ${relativeDay(day)}`))
      : h('div', { class: 'rowitem__time' }, h('b', {}, fmtDayNum(b.boarding_start)), h('span', {}, fmtWeekday(b.boarding_start)))) : h('span'),
    h('div', { class: 'rowitem__main' },
      h('div', { class: 'rowitem__title' }, h('a', { href: href(workspacePath(b)) }, b.pet_name), chip(b.status), (b.flags || []).map(flagTag)),
      h('div', { class: 'rowitem__meta' }, h('span', {}, icon(g ? 'scissors' : 'bed'), b.service_name), h('span', {}, scheduleText(b)),
        h('span', {}, icon('user'), b.customer_name),
        b.assigned_staff_name ? h('span', {}, icon('users'), b.assigned_staff_name) : null,
        b.accommodation_name ? h('span', {}, icon('home_care'), b.accommodation_name) : null)),
    h('div', { class: 'rowitem__side' }, actions || h('a', { class: 'btn btn--secondary btn--sm', href: href(workspacePath(b)) }, b.status === 'SUBMITTED' ? 'Review' : 'Open')));
}

/** Booking table for dense Admin lists (cards on phones). */
export function bookingTable(list, { caption } = {}) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' },
    caption ? h('caption', { class: 'visually-hidden' }, caption) : null,
    h('thead', {}, h('tr', {}, ['Pet and owner', 'Service', 'When', 'Status', 'Team member', 'Next step', ''].map((c, i) => h('th', { scope: 'col', class: i === 6 ? 'col-actions' : null }, c ? c : h('span', { class: 'visually-hidden' }, 'Actions'))))),
    h('tbody', {}, list.map((b) => h('tr', {},
      h('td', { 'data-label': 'Pet' }, h('div', { class: 'cell-pet' }, avatar(b.pet_name, 'avatar--sm'), h('div', {}, h('a', { class: 'cell-pet__name', href: href(workspacePath(b)) }, b.pet_name), h('div', { class: 'cell-pet__sub' }, b.customer_name)))),
      h('td', { 'data-label': 'Service' }, h('span', { class: 'service-mark' }, icon(b.booking_type === 'GROOMING' ? 'scissors' : 'bed'), b.service_name)),
      h('td', { 'data-label': 'When', class: 'cell-when' }, scheduleText(b)),
      h('td', { 'data-label': 'Status' }, h('div', { class: 'row row--wrap', style: { gap: '6px' } }, chip(b.status), (b.flags || []).map(flagTag))),
      h('td', { 'data-label': 'Team' }, b.assigned_staff_name || h('span', { class: 'muted' }, b.booking_type === 'GROOMING' ? 'Not assigned' : 'Optional')),
      h('td', { 'data-label': 'Next' }, h('span', { class: 'small' }, adminNext(b))),
      h('td', { class: 'col-actions' }, h('a', { class: 'btn btn--secondary btn--sm', href: href(workspacePath(b)) }, b.status === 'SUBMITTED' ? 'Review' : 'Open')))))));
}

/** Drill-down: show exactly the records behind a count. */
export function drillDown(title, items, definition) {
  const { body } = drawer({ title: `${title} (${items.length})` });
  if (definition) body.append(h('p', { class: 'small muted' }, definition));
  body.append(items.length ? h('div', { class: 'panel' }, h('div', { class: 'rows' }, items.map((b) => opRow(b))))
    : h('div', { class: 'panel' }, empty({ icon: 'check_circle', title: 'Nothing here right now', text: 'No records match this definition at the moment.', compact: true })));
}
