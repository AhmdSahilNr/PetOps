// Admin Staff work \u2014 current and upcoming responsibility per active Staff member (open responsibilities only).
import { h, icon, replace } from '../core/dom.js';
import { get } from '../core/api.js';
import { href } from '../core/router.js';
import { pageHead, panel, empty, skeleton, errorState, avatar, meter, updatedStamp, notice } from '../core/ui.js';
import { opRow } from './common.js';

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(6));
  const stamp = updatedStamp(() => ctx.refresh());
  root.append(pageHead({ title: 'Staff work', context: stamp.el,
    actions: h('a', { class: 'btn btn--secondary', href: href('/settings/staff') }, icon('settings'), 'Staff accounts') }), host);
  let ops, staff;
  try { [ops, staff] = await Promise.all([get('/admin/operations'), get('/admin/staff')]); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const inactive = staff.filter((s) => !s.is_active);
  const max = Math.max(1, ...ops.staff_work.map((s) => s.now.length + s.next_7_days.length));
  const unassigned = ops.needs_decision.filter((b) => b.flags.includes('needs_staff'));
  replace(host,
    unassigned.length ? h('div', { style: { 'margin-top': '16px' } }, panel({ title: 'Grooming requests without a groomer', icon: 'alert', count: unassigned.length, flush: true,
      body: h('div', { class: 'rows' }, unassigned.map((b) => opRow(b))) })) : null,
    h('div', { class: 'grid grid--2', style: { 'margin-top': '16px' } }, ops.staff_work.length ? ops.staff_work.map((s) => panel({
      title: h('span', { class: 'row' }, avatar(s.name, 'avatar--sm avatar--staff'), s.name), headingLevel: 'h2',
      actions: h('span', { class: 'small muted' }, `${s.now.length} now, ${s.next_7_days.length} next 7 days`), flush: true,
      body: h('div', {}, h('div', { style: { padding: '12px 20px' } }, meter(s.now.length + s.next_7_days.length, max)),
        s.now.length ? [h('div', { class: 'lane-title' }, icon('home_care'), 'Responsible now'), s.now.map((b) => opRow(b))] : null,
        s.next_7_days.length ? [h('div', { class: 'lane-title' }, icon('calendar'), 'Next 7 days'), s.next_7_days.map((b) => opRow(b))] : null,
        !s.now.length && !s.next_7_days.length ? h('div', { class: 'lane-empty' }, 'No current or upcoming responsibility.') : null) }))
      : h('div', { class: 'panel' }, empty({ icon: 'users', title: 'No active team members', action: h('a', { class: 'btn btn--secondary', href: href('/settings/staff') }, 'Add a team member') }))),
    inactive.length ? h('p', { class: 'small muted', style: { 'margin-top': '16px' } }, `${inactive.length} inactive account${inactive.length === 1 ? '' : 's'} not shown. Inactive accounts cannot sign in or be assigned.`) : null);
}
