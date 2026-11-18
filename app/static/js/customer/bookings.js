// My bookings \u2014 Upcoming & requested / In care / Past / Cancelled & rejected.
import { h, replace } from '../core/dom.js';
import { href, replaceQuery } from '../core/router.js';
import { pageHead, segmented, empty, skeleton, errorState } from '../core/ui.js';
import { loadCustomer, upcoming, inCare, finished, closed } from './data.js';
import { bookingRow } from './common.js';

const TABS = [
  ['upcoming', 'Upcoming', 'clock'], ['care', 'In care', 'home_care'], ['past', 'Past', 'check_circle'], ['closed', 'Cancelled and rejected', 'ban'],
];

export async function render(root, ctx) {
  let tab = TABS.some(([k]) => k === ctx.query.tab) ? ctx.query.tab : 'upcoming';
  const host = h('div', {}, skeleton(6));
  root.append(pageHead({ title: 'My bookings' }), host);
  let data;
  try { data = await loadCustomer(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const groups = { upcoming: upcoming(data.bookings), care: inCare(data.bookings), past: finished(data.bookings), closed: closed(data.bookings) };
  if (tab === 'upcoming' && !groups.upcoming.length && groups.care.length) tab = 'care';
  const draw = () => {
    const list = groups[tab];
    const emptyCopy = {
      upcoming: ['No upcoming bookings', 'Requests and confirmed bookings will appear here.'],
      care: ['No pets in our care right now', 'Grooming in progress and current boarding stays appear here.'],
      past: ['No past bookings yet', 'Completed grooming and stays are kept here as your history.'],
      closed: ['Nothing cancelled or rejected', 'Cancelled bookings and requests we could not accept are listed here.'],
    }[tab];
    replace(host,
      h('div', { style: { 'margin-bottom': '16px' } }, segmented(TABS.map(([value, label, icon]) => ({ value, label, icon, count: groups[value].length })), tab,
        (v) => { tab = v; replaceQuery({ tab: v }); draw(); }, 'Booking groups')),
      h('section', { class: 'panel' }, list.length ? h('div', { class: 'rows' }, list.map(bookingRow))
        : empty({ icon: 'calendar', title: emptyCopy[0], text: emptyCopy[1], action: tab === 'upcoming' ? h('a', { class: 'btn', href: href('/book') }, 'Book a service') : null })));
  };
  draw();
}
