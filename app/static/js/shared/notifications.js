// One notification experience for Customers and Staff. The server decides whether a booking link is still
// permitted (can_view_booking); the linked page re-checks access, so a link can never restore lost access.
import { h, icon, replace } from '../core/dom.js';
import { get, post, qs } from '../core/api.js';
import { href } from '../core/router.js';
import { pageHead, segmented, empty, skeleton, errorState, button, busy, toast } from '../core/ui.js';
import { fmtTime, mytDate, relativeDay, fmtDate, scheduleFromSnapshot } from '../core/format.js';

const KIND_ICON = { BOOKING_SUBMITTED: 'clock', BOOKING_CONFIRMED: 'check', BOOKING_RECONFIRMED: 'check', BOOKING_REJECTED: 'x_circle',
  RESCHEDULE_REJECTED: 'x_circle', BOOKING_RESCHEDULED: 'swap', BOOKING_CANCELLED: 'ban', BOOKING_REMINDER: 'bell',
  STAFF_ASSIGNED: 'user', STAFF_REASSIGNED: 'swap' };

export async function render(root, ctx) {
  let filter = ctx.query.show === 'unread' ? 'unread' : 'all';
  const isStaff = ctx.user.role === 'STAFF';
  const listHost = h('div', {}, skeleton(5));
  const markAll = button('Mark all as read', { variant: 'secondary', size: 'sm', icon: 'check' });
  const seg = h('div');
  root.append(pageHead({ title: 'Notifications', actions: markAll }),
    h('div', { class: 'row row--wrap', style: { 'margin-bottom': '16px' } }, seg), listHost);
  let data;
  const load = async () => {
    data = await get(`/notifications${qs({ limit: 100 })}`);
    if (!ctx.alive()) return;
    draw();
    ctx.shell && ctx.shell.setBadge('notifications', data.unread_count);
  };
  const draw = () => {
    replace(seg, segmented([{ value: 'all', label: 'All', count: data.items.length }, { value: 'unread', label: 'Unread', count: data.unread_count }],
      filter, (v) => { filter = v; draw(); }, 'Show'));
    markAll.disabled = !data.unread_count;
    const items = data.items.filter((n) => filter === 'all' || !n.read_at);
    if (!items.length) {
      replace(listHost, h('div', { class: 'panel' }, empty({ icon: 'bell', title: filter === 'unread' ? 'You are all caught up' : 'No notifications yet',
        text: isStaff ? 'You will be notified here when work is assigned to you or changes.' : 'Booking confirmations, changes and reminders will appear here.' })));
      return;
    }
    const groups = new Map();
    for (const n of items) { const d = mytDate(n.created_at); if (!groups.has(d)) groups.set(d, []); groups.get(d).push(n); }
    replace(listHost, [...groups].map(([day, list]) => h('section', { class: 'notif-group' },
      h('h2', { class: 'notif-group__day' }, `${relativeDay(day)}${['Today', 'Yesterday'].includes(relativeDay(day)) ? '' : `, ${fmtDate(day)}`}`),
      h('ul', { class: 'panel notif-list' }, list.map((n) => item(n))))));
  };
  const markRead = async (n) => { if (n.read_at) return; const r = await post(`/notifications/${n.id}/read`); Object.assign(n, r); data.unread_count = Math.max(0, data.unread_count - 1); };
  const item = (n) => {
    const target = n.can_view_booking ? (isStaff ? `/work/${n.booking_type.toLowerCase()}/${n.booking_id}` : `/bookings/${n.booking_type.toLowerCase()}/${n.booking_id}`) : null;
    const context = [n.service_name, n.schedule ? scheduleFromSnapshot(n.schedule) : null].filter(Boolean).join(', ');
    const open = target ? h('a', { class: 'btn btn--secondary btn--sm', href: href(target), on: { click: () => { markRead(n).catch(() => {}); } } }, n.cta_label || 'Open') : null;
    const readBtn = !n.read_at ? button('Mark read', { variant: 'ghost', size: 'sm', onClick: async (e) => {
      await busy(e.currentTarget, async () => { await markRead(n); draw(); ctx.shell && ctx.shell.setBadge('notifications', data.unread_count); });
    } }) : null;
    return h('li', { class: ['notif', !n.read_at && 'is-unread'] },
      h('span', { class: 'notif__icon' }, icon(KIND_ICON[n.kind] || 'bell')),
      h('div', { class: 'notif__main' },
        h('div', { class: 'notif__title' }, !n.read_at ? h('span', { class: 'notif__dot' }, h('span', { class: 'visually-hidden' }, 'Unread: ')) : null, n.pet_name ? `${n.pet_name}: ${n.title.replace(` \u2014 ${n.pet_name}`, '').replace(/^./, (c) => c.toLowerCase())}` : n.title),
        h('p', { class: 'notif__msg' }, n.message),
        context ? h('p', { class: 'notif__ctx' }, context) : null,
        !n.can_view_booking && isStaff ? h('p', { class: 'notif__ctx' }, 'Details are hidden because this work is no longer assigned to you.') : null),
      h('div', { class: 'notif__side' }, h('time', { class: 'notif__time', datetime: n.created_at }, fmtTime(n.created_at)), open, readBtn));
  };
  markAll.addEventListener('click', () => busy(markAll, async () => {
    for (const n of data.items.filter((x) => !x.read_at)) await markRead(n);
    draw(); ctx.shell && ctx.shell.setBadge('notifications', 0); toast('All notifications marked as read.');
  }));
  try { await load(); } catch (e) { if (ctx.alive()) replace(listHost, errorState(e, ctx.refresh)); }
}
