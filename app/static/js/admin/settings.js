// Admin Settings \u2014 "how PetOps works", kept apart from daily operations (directive 03 \u00a710, \u00a724, \u00a743).
// Each section states what it changes, shows the current value, validates input and confirms risky changes.
import { h, icon, replace } from '../core/dom.js';
import { get, post, put, qs } from '../core/api.js';
import { href } from '../core/router.js';
import { pageHead, panel, button, busy, confirmDialog, drawer, field, input, select, notice, toast, skeleton, errorState, empty, pips, avatar, chip } from '../core/ui.js';
import { fmtStamp, minutesText, plural } from '../core/format.js';

const SECTIONS = {
  '/settings/services': { title: 'Services', icon: 'tag', intro: 'The grooming and boarding services customers can book. Inactive services stay in history but cannot be booked. Order controls how they are listed.' },
  '/settings/staff': { title: 'Staff accounts', icon: 'user', intro: 'Team sign-in accounts. A team member can be assigned when the account is active and they have no overlapping PetOps work. Deactivating signs them out and is refused while they still have current or upcoming work.' },
  '/settings/accommodation': { title: 'Boarding setup', icon: 'bed', intro: 'Accommodation units and how many pets each can hold. Capacity drives availability for new stays. A unit cannot be reduced below, or deactivated with, pets already allocated to it.' },
  '/settings/reminders': { title: 'Reminders', icon: 'bell', intro: 'In-app reminders sent to customers before a confirmed booking. Changes apply to reminders created from now on.' },
  '/settings/activity': { title: 'Change log', icon: 'note', intro: 'A record of configuration changes: who changed what and when. Booking activity is on each booking\u2019s timeline.' },
};

export async function render(root, ctx) {
  const sec = SECTIONS[ctx.path] || SECTIONS['/settings/services'];
  const host = h('div', {}, skeleton(6));
  root.append(pageHead({ title: sec.title, crumbs: [{ label: 'Settings' }, { label: sec.title }] }),
    h('div', { class: 'settings-intro' }, icon(sec.icon), h('p', {}, sec.intro)), host);
  try {
    const view = { '/settings/services': services, '/settings/staff': staff, '/settings/accommodation': accommodation, '/settings/reminders': reminders, '/settings/activity': activity }[ctx.path] || services;
    const content = await view(ctx);
    if (ctx.alive()) replace(host, content);
  } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); }
}

const activeChip = (on) => h('span', { class: `tag ${on ? 'tag--ok' : ''}` }, icon(on ? 'check' : 'ban'), on ? 'Active' : 'Inactive');
const formDrawer = (title, fields, submitLabel, onSubmit, extra) => {
  const { body, close } = drawer({ title });
  const err = h('div', { hidden: true });
  const save = button(submitLabel, { type: 'submit' });
  body.append(h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
    e.preventDefault(); err.hidden = true;
    const r = await busy(save, () => onSubmit(), { errorTarget: err });
    if (r) close();
  } } }, fields, extra || null, err, h('div', { class: 'form-actions' }, save, button('Cancel', { variant: 'secondary', onClick: close }))));
  return close;
};

// ---------- Services ----------
async function services(ctx) {
  const list = await get('/admin/services');
  const edit = (s) => {
    const isNew = !s; const type = isNew ? 'GROOMING' : s.service_type;
    const name = input({ value: s ? s.name : '', maxLength: 120, required: true });
    const typeSel = select([{ value: 'GROOMING', label: 'Grooming' }, { value: 'BOARDING', label: 'Boarding' }], { value: type, disabled: !isNew });
    const dur = input({ type: 'number', min: 1, step: 5, value: s && s.duration_minutes ? String(s.duration_minutes) : '60', inputMode: 'numeric' });
    const order = input({ type: 'number', min: 0, step: 1, value: s ? String(s.display_order) : '0', inputMode: 'numeric' });
    const active = h('input', { type: 'checkbox', checked: s ? s.is_active : true });
    const durField = field({ label: 'Duration (minutes)', input: dur, hint: 'Grooming only. Used to check a groomer is free for the whole appointment.' });
    const sync = () => { durField.hidden = typeSel.value !== 'GROOMING'; };
    typeSel.addEventListener('change', sync); sync();
    formDrawer(isNew ? 'Add service' : `Edit ${s.name}`, [field({ label: 'Name', input: name }), field({ label: 'Service type', input: typeSel, hint: isNew ? null : 'The type of an existing service cannot change.' }),
      durField, field({ label: 'Display order', input: order, hint: 'Lower numbers are listed first within the type.' }), h('label', { class: 'check' }, active, 'Active (customers can book it)')],
    isNew ? 'Add service' : 'Save changes', async () => {
      const grooming = typeSel.value === 'GROOMING';
      const payload = { name: name.value.trim(), is_active: active.checked, display_order: Number(order.value || 0), ...(grooming ? { duration_minutes: Number(dur.value) } : {}) };
      if (!payload.name) throw new Error('Enter a service name.');
      if (grooming && !(payload.duration_minutes > 0)) throw new Error('Enter a duration in minutes.');
      if (s && s.is_active && !active.checked && !(await confirmDialog({ title: `Make ${s.name} inactive?`, confirmLabel: 'Make inactive', cancelLabel: 'Keep active', danger: true,
        body: 'Customers will no longer be able to book it. Existing bookings and history are not changed.' }))) return undefined;
      if (isNew) await post('/admin/services', { ...payload, service_type: typeSel.value }); else await put(`/admin/services/${s.id}`, payload);
      toast(isNew ? 'Service added.' : 'Service saved.'); ctx.refresh(); return true;
    });
  };
  const group = (type, label, ic) => {
    const items = list.filter((s) => s.service_type === type);
    return panel({ title: label, icon: ic, count: items.length, flush: true, body: items.length ? h('div', {}, items.map((s) => h('div', { class: 'setting-row' },
      h('div', {}, h('b', {}, s.name), h('div', { class: 'sub' }, activeChip(s.is_active), s.duration_minutes ? h('span', {}, minutesText(s.duration_minutes)) : null,
        h('span', {}, `Order ${s.display_order}`), s.updated_at ? h('span', {}, `Updated ${fmtStamp(s.updated_at)}`) : null)),
      button('Edit', { variant: 'secondary', size: 'sm', icon: 'edit', onClick: () => edit(s) }))))
      : empty({ icon: ic, title: `No ${label.toLowerCase()} services`, compact: true }) });
  };
  return h('div', { class: 'stack' }, h('div', { class: 'row' }, button('Add service', { icon: 'plus', onClick: () => edit(null) })),
    group('GROOMING', 'Grooming', 'scissors'), group('BOARDING', 'Boarding', 'bed'));
}

// ---------- Staff accounts ----------
async function staff(ctx) {
  const list = await get('/admin/staff');
  const edit = (s) => {
    const isNew = !s;
    const name = input({ value: s ? s.display_name || '' : '', maxLength: 120, autocomplete: 'off' });
    const email = input({ type: 'email', value: s ? s.email : '', required: true, autocomplete: 'off' });
    const pw = input({ type: 'password', minLength: 10, maxLength: 128, autocomplete: 'new-password' });
    const active = h('input', { type: 'checkbox', checked: s ? s.is_active : true });
    const legacy = h('div');
    if (s) get(`/admin/staff/${s.id}/availability`).then((w) => { if (w.length) replace(legacy, notice('info', 'Legacy availability records', `${plural(w.length, 'older availability window')} recorded before 14 Nov ${w.length === 1 ? 'is' : 'are'} kept read-only. They no longer affect assignment.`)); }).catch(() => {});
    formDrawer(isNew ? 'Add team member' : `Edit ${s.display_name || s.email}`, [field({ label: 'Display name', input: name, hint: 'Shown on assignments and history.' }),
      field({ label: 'Sign-in email', input: email }), field({ label: isNew ? 'Temporary password' : 'New password (optional)', input: pw, hint: 'At least 10 characters. Changing it signs the person out.' }),
      h('label', { class: 'check' }, active, 'Active (can sign in and be assigned)')], isNew ? 'Add team member' : 'Save changes', async () => {
      if (!email.value.includes('@')) throw new Error('Enter a valid email address.');
      if ((isNew || pw.value) && pw.value.length < 10) throw new Error('Passwords need at least 10 characters.');
      const payload = { display_name: name.value.trim() || null, email: email.value.trim(), is_active: active.checked, ...(pw.value ? { password: pw.value } : {}) };
      if (s && s.is_active && !active.checked && !(await confirmDialog({ title: `Deactivate ${s.display_name || s.email}?`, confirmLabel: 'Deactivate', cancelLabel: 'Keep active', danger: true,
        body: 'They will be signed out and cannot be assigned. PetOps refuses this while they still have current or upcoming work; reassign it first.' }))) return undefined;
      if (isNew) await post('/admin/staff', { ...payload, password: pw.value }); else await put(`/admin/staff/${s.id}`, payload);
      toast(isNew ? 'Team member added.' : 'Account saved.'); ctx.refresh(); return true;
    }, legacy);
  };
  return h('div', { class: 'stack' }, h('div', { class: 'row' }, button('Add team member', { icon: 'plus', onClick: () => edit(null) })),
    panel({ title: 'Team accounts', icon: 'users', count: list.length, flush: true, body: list.length ? h('div', {}, list.map((s) => h('div', { class: 'setting-row' },
      h('div', { class: 'row' }, avatar(s.display_name || s.email, 'avatar--sm avatar--staff'), h('div', {}, h('b', {}, s.display_name || 'Name not recorded'),
        h('div', { class: 'sub' }, h('span', {}, s.email), activeChip(s.is_active), h('span', {}, `Added ${fmtStamp(s.created_at)}`)))),
      button('Edit', { variant: 'secondary', size: 'sm', icon: 'edit', onClick: () => edit(s) }))))
      : empty({ icon: 'users', title: 'No team accounts yet', compact: true }) }),
    notice('info', 'No separate availability schedule', 'Since the approved 14 November change, assignment uses active status and booking dates only. Each team member can see their own assigned work in Agenda; you can see everyone\u2019s on Staff work.'));
}

// ---------- Boarding setup ----------
async function accommodation(ctx) {
  const [units, ops] = await Promise.all([get('/admin/accommodations'), get('/admin/operations')]);
  const now = new Map(ops.capacity_now.units.map((u) => [u.id, u]));
  const edit = (u) => {
    const isNew = !u;
    const name = input({ value: u ? u.name : '', maxLength: 120, required: true });
    const cat = input({ value: u ? u.category : '', maxLength: 120, required: true, placeholder: 'For example, Suite or Cattery' });
    const cap = input({ type: 'number', min: 1, step: 1, value: u ? String(u.capacity) : '1', inputMode: 'numeric' });
    const notes = h('textarea', { class: 'textarea', rows: 3, value: u && u.notes ? u.notes : '' });
    const active = h('input', { type: 'checkbox', checked: u ? u.is_active : true });
    formDrawer(isNew ? 'Add accommodation' : `Edit ${u.name}`, [field({ label: 'Name', input: name }), field({ label: 'Category', input: cat }),
      field({ label: 'Capacity (pets)', input: cap, hint: 'How many pets can stay in this unit at the same time.' }), field({ label: 'Notes (optional)', input: notes }),
      h('label', { class: 'check' }, active, 'Active (available for new stays)')], isNew ? 'Add accommodation' : 'Save changes', async () => {
      const payload = { name: name.value.trim(), category: cat.value.trim(), capacity: Number(cap.value), is_active: active.checked, notes: notes.value.trim() || null };
      if (!payload.name || !payload.category) throw new Error('Enter a name and a category.');
      if (!(payload.capacity >= 1)) throw new Error('Capacity must be at least 1.');
      if (u && (payload.capacity < u.capacity || (u.is_active && !payload.is_active)) && !(await confirmDialog({ title: 'Reduce available places?', confirmLabel: 'Save change', cancelLabel: 'Go back', danger: true,
        body: 'Fewer places will be offered for new stays. PetOps refuses the change if it would invalidate pets already allocated.' }))) return undefined;
      if (isNew) await post('/admin/accommodations', payload); else await put(`/admin/accommodations/${u.id}`, payload);
      toast(isNew ? 'Accommodation added.' : 'Accommodation saved.'); ctx.refresh(); return true;
    });
  };
  const total = units.filter((u) => u.is_active).reduce((s, u) => s + u.capacity, 0);
  return h('div', { class: 'stack' }, h('div', { class: 'row row--wrap row--between' }, button('Add accommodation', { icon: 'plus', onClick: () => edit(null) }),
    h('span', { class: 'small muted' }, `${plural(total, 'place')} across ${plural(units.filter((u) => u.is_active).length, 'active unit')}`)),
  panel({ title: 'Accommodation units', icon: 'bed', count: units.length, flush: true, body: units.length ? h('div', {}, units.map((u) => {
    const n = now.get(u.id) || { occupied: 0 };
    return h('div', { class: 'setting-row' }, h('div', {}, h('b', {}, u.name), h('div', { class: 'sub' }, h('span', {}, u.category), activeChip(u.is_active),
      h('span', {}, `${n.occupied} in care now`), u.notes ? h('span', {}, u.notes) : null), h('div', { style: { 'margin-top': '6px' } }, pips(u.capacity, n.occupied, n.occupied))),
    button('Edit', { variant: 'secondary', size: 'sm', icon: 'edit', onClick: () => edit(u) }));
  })) : empty({ icon: 'bed', title: 'No accommodation yet', text: 'Add a unit so customers can book stays.', compact: true }) }));
}

// ---------- Reminders ----------
async function reminders(ctx) {
  const s = await get('/admin/notification-settings');
  const enabled = h('input', { type: 'checkbox', checked: s.enabled });
  const lead = input({ type: 'number', min: 1, max: 525600, step: 1, value: s.lead_minutes ? String(s.lead_minutes) : '', inputMode: 'numeric' });
  const leadField = field({ label: 'Send reminders this many minutes before', input: lead, hint: 'For example 1440 for one day. Boarding uses midnight on the check-in date as its reference.' });
  const save = button('Save reminder settings', { type: 'submit' });
  const err = h('div', { hidden: true });
  const run = button('Check for due reminders now', { variant: 'secondary', icon: 'refresh' });
  run.addEventListener('click', async () => { const r = await busy(run, () => post('/admin/reminders/run', {})); if (r) toast(r.created ? `${plural(r.created, 'reminder')} created.` : 'No reminders were due.'); });
  return h('div', { class: 'grid grid--main-rail' },
    panel({ title: 'Reminder settings', icon: 'bell', body: h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
      e.preventDefault(); leadField.setError(''); err.hidden = true;
      const minutes = lead.value ? Number(lead.value) : null;
      if (enabled.checked && !(minutes >= 1)) { leadField.setError('Enter a lead time before turning reminders on.'); lead.focus(); return; }
      const r = await busy(save, () => put('/admin/notification-settings', { enabled: enabled.checked, lead_minutes: minutes }), { errorTarget: err });
      if (r) { toast('Reminder settings saved.'); ctx.refresh(); }
    } } }, h('label', { class: 'check' }, enabled, 'Send reminders for confirmed bookings'), leadField, err, h('div', { class: 'form-actions' }, save)) }),
    h('div', { class: 'stack' },
      panel({ title: 'Current setting', body: h('div', { class: 'current-value' }, h('span', { class: 'small muted' }, 'Reminders are'),
        h('b', {}, s.enabled ? `On, ${minutesText(s.lead_minutes)} before` : 'Off'), s.updated_at ? h('span', { class: 'small muted' }, `Last changed ${fmtStamp(s.updated_at)}`) : null) }),
      panel({ title: 'Send due reminders', body: h('div', { class: 'stack stack--sm' }, h('p', { class: 'small muted' }, 'PetOps checks automatically. Use this to check immediately; a reminder is never sent twice.'), run) })));
}

// ---------- Change log ----------
const ACTION = { STAFF_CREATED: 'Team member added', STAFF_UPDATED: 'Team account changed', SERVICE_CREATED: 'Service added', SERVICE_UPDATED: 'Service changed', REMINDER_SETTINGS_UPDATED: 'Reminder settings changed' };
function describe(e) {
  const o = (e.details && e.details.old) || {}, n = (e.details && e.details.new) || {};
  const parts = [];
  if (n.display_name !== undefined && o.display_name !== n.display_name && e.action !== 'STAFF_CREATED') parts.push(`name ${o.display_name || 'not set'} to ${n.display_name || 'not set'}`);
  if (n.name !== undefined && o.name !== n.name && o.name) parts.push(`name ${o.name} to ${n.name}`);
  if (n.is_active !== undefined && o.is_active !== undefined && o.is_active !== n.is_active) parts.push(n.is_active ? 'activated' : 'deactivated');
  if (n.duration_minutes !== undefined && o.duration_minutes !== undefined && o.duration_minutes !== n.duration_minutes) parts.push(`duration ${o.duration_minutes} to ${n.duration_minutes} minutes`);
  if (n.enabled !== undefined && (o.enabled !== n.enabled || o.lead_minutes !== n.lead_minutes)) parts.push(n.enabled ? `on, ${n.lead_minutes} minutes before` : 'turned off');
  if (e.details && e.details.password_changed) parts.push('password reset');
  return parts.join('; ') || (n.name || n.display_name || n.email || '');
}
async function activity() {
  const list = await get(`/admin/management-history${qs({ limit: 100 })}`);
  return panel({ title: 'Recent changes', icon: 'note', count: list.length, flush: true, body: list.length ? h('div', {}, list.map((e) => h('div', { class: 'setting-row' },
    h('div', {}, h('b', {}, ACTION[e.action] || e.action), h('div', { class: 'sub' }, h('span', {}, describe(e)), h('span', {}, `by ${e.actor_name}`))),
    h('span', { class: 'small muted nowrap' }, fmtStamp(e.created_at)))))
    : empty({ icon: 'note', title: 'No configuration changes recorded yet', compact: true }) });
}
void href; void chip;
