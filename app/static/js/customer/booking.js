// Customer booking detail \u2014 status, what happens next, permitted changes, customer-language timeline.
import { h, replace, nextId } from '../core/dom.js';
import { get, post } from '../core/api.js';
import { href, go } from '../core/router.js';
import { pageHead, panel, chip, serviceMark, tracker, timeline, button, busy, confirmDialog, drawer, field, input, notice, toast, skeleton, errorState, empty } from '../core/ui.js';
import { scheduleText, fmtStamp, mytDate, mytTimeOf, mytInstant, addDays, fmtDay, nights, plural } from '../core/format.js';
import { customerNextStep, CHANGEABLE, SERVICE } from '../core/labels.js';

export async function render(root, ctx) {
  const type = ctx.params.type === 'boarding' ? 'boarding' : 'grooming';
  const host = h('div', {}, skeleton(8));
  root.append(host);
  let d;
  try { d = await get(`/${type}/bookings/${encodeURIComponent(ctx.params.id)}`); }
  catch (e) {
    if (!ctx.alive()) return;
    replace(host, pageHead({ title: 'Booking not available', crumbs: [{ label: 'My bookings', href: href('/bookings') }, { label: 'Not available' }] }),
      e.status === 404 ? h('div', { class: 'panel' }, empty({ icon: 'ban', title: 'This booking is not available to you', text: 'It may belong to another account, or the link is incorrect.',
        action: h('a', { class: 'btn btn--secondary', href: href('/bookings') }, 'Back to my bookings') })) : errorState(e, ctx.refresh));
    return;
  }
  if (!ctx.alive()) return;
  const b = { ...d.booking, pet_name: d.pet_name, service_name: d.service_name };
  const next = customerNextStep(b, d.pet_name);
  const changeable = CHANGEABLE.has(b.status);
  const changeActions = () => [button('Change dates', { variant: 'secondary', icon: 'calendar', onClick: () => openReschedule(b, ctx) }),
    button('Cancel booking', { variant: 'danger-quiet', icon: 'ban', onClick: (e) => cancel(e.currentTarget, b, ctx) })];
  const rebook = ['COMPLETED', 'REJECTED', 'CANCELLED', 'CHECKED_OUT'].includes(b.status)
    ? () => [h('a', { class: 'btn', href: href('/book', { type: b.booking_type, pet: b.pet_id }) }, 'Book again')] : null;
  const actions = changeable ? changeActions() : rebook ? rebook() : [];
  const notes = [];
  if (d.grooming_record && d.grooming_record.service_notes) notes.push({ text: d.grooming_record.service_notes, at: d.grooming_record.completed_at, label: 'From your groomer' });
  for (const n of d.stay_notes || []) notes.push({ text: n.note, at: n.created_at, label: 'Stay update' });
  replace(host,
    pageHead({ title: h('span', { class: 'detail-title' }, `${d.pet_name}`, chip(b.status)), crumbs: [{ label: 'My bookings', href: href('/bookings') }, { label: `${d.pet_name}, ${d.service_name}` }],
      context: [serviceMark(b.booking_type, d.service_name), h('span', {}, scheduleText(b))], actions: rebook ? rebook() : null }),
    h('div', { class: ['detail-grid', actions.length && 'has-sticky'] },
      h('div', { class: 'stack' },
        panel({ title: 'Progress', icon: 'list', body: h('div', { class: 'status-block' }, tracker(b), h('div', { class: 'next-step' }, h('b', {}, next.title), h('p', {}, next.text))) }),
        notes.length ? panel({ title: b.booking_type === 'GROOMING' ? 'Notes from the team' : 'Stay updates', icon: 'note',
          body: h('div', { class: 'stack stack--sm' }, notes.reverse().map((n) => h('div', { class: 'note-card' }, h('p', {}, n.text), h('div', { class: 'meta' }, `${n.label}, ${fmtStamp(n.at)}`)))) }) : null,
        panel({ title: 'Activity', icon: 'history', body: timeline(d.timeline) })),
      h('div', { class: 'stack' },
        panel({ title: 'Booking details', body: h('dl', { class: 'facts' },
          [['Pet', d.pet_name], ['Service', `${SERVICE[b.booking_type].label}: ${d.service_name}`], ['When', scheduleText(b)], ['Requested', fmtStamp(b.created_at)],
            ['Reference', b.id.slice(0, 8).toUpperCase()]].map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))) }),
        changeable ? panel({ title: 'Need a change?', body: h('div', { class: 'stack stack--sm' },
          h('p', { class: 'small muted' }, 'You can change dates or cancel until the service starts. A change returns the booking to Requested so PetOps can confirm it again.'),
          h('div', { class: 'row row--wrap' }, changeActions())) }) : null)),
    actions.length ? h('div', { class: 'sticky-actions' }, actions) : null);
}

async function cancel(btn, b, ctx) {
  const ok = await confirmDialog({ title: 'Cancel this booking?', danger: true, confirmLabel: 'Cancel booking', cancelLabel: 'Keep booking',
    body: `${b.pet_name}'s ${b.service_name} on ${scheduleText(b)} will be cancelled. This cannot be undone; you can make a new booking later.` });
  if (!ok) return;
  const done = await busy(btn, () => post(`/bookings/${b.id}/cancel`));
  if (done) { toast('Booking cancelled.'); ctx.refresh(); }
}

function openReschedule(b, ctx) {
  const g = b.booking_type === 'GROOMING';
  const { body, close } = drawer({ title: 'Change dates' });
  const err = h('div', { hidden: true, role: 'alert' });
  const hintId = nextId('hint');
  const save = button('Send new dates', { type: 'submit' });
  let read;
  let inputs;
  if (g) {
    const date = input({ type: 'date', value: mytDate(b.grooming_start), min: mytDate(), required: true });
    const time = input({ type: 'time', value: mytTimeOf(b.grooming_start), step: 900, required: true });
    inputs = [date, time];
    read = () => ({ grooming_start: mytInstant(date.value, time.value) });
    body.append(h('div', { class: 'form-grid form-grid--2' }, field({ label: 'New date', input: date }), field({ label: 'New start time (Malaysia time)', input: time })));
  } else {
    const a = input({ type: 'date', value: b.boarding_start, min: mytDate(), required: true });
    const z = input({ type: 'date', value: b.boarding_end, min: addDays(b.boarding_start, 1), required: true });
    a.addEventListener('input', () => { z.min = addDays(a.value || mytDate(), 1); });
    inputs = [a, z];
    read = () => ({ boarding_start: a.value, boarding_end: z.value });
    body.append(h('div', { class: 'form-grid form-grid--2' }, field({ label: 'New check-in date', input: a }), field({ label: 'New check-out date', input: z })));
  }
  const original = JSON.stringify(read());
  const hint = h('p', { class: 'action-hint', id: hintId }, 'Change the date or time to send a new request.');
  const sync = () => {
    const same = JSON.stringify(read()) === original || inputs.some((i) => !i.value);
    save.disabled = same; hint.hidden = !same;
    if (same) save.setAttribute('aria-describedby', hintId); else save.removeAttribute('aria-describedby');
  };
  inputs.forEach((i) => i.addEventListener('input', sync));
  body.prepend(notice('warn', 'What a change means', `${b.pet_name}'s booking returns to Requested and its confirmed ${g ? 'time and groomer are' : 'place is'} released until PetOps confirms the new ${g ? 'time' : 'dates'}.`));
  body.append(err, h('form', { class: 'form-actions', on: { submit: async (e) => {
    e.preventDefault(); err.hidden = true;
    const payload = read();
    if (!g && payload.boarding_end <= payload.boarding_start) { replace(err, notice('danger', 'Check the dates', 'Check-out must be after check-in.')); err.hidden = false; return; }
    const r = await busy(save, () => post(`/bookings/${b.id}/reschedule`, payload), { errorTarget: err });
    if (r) { close(); toast(g ? 'New time sent. PetOps will confirm it.' : `New dates sent (${plural(nights(payload.boarding_start, payload.boarding_end), 'night')}). PetOps will confirm them.`); ctx.refresh(); }
  } } }, save, button('Keep current dates', { variant: 'secondary', onClick: close })), hint);
  sync();
  void fmtDay; void go;
}
