// Admin booking workspace \u2014 prepare, decide, change, (fallback) fulfil, and audit one booking.
// Every action calls the canonical endpoint; the server enforces BR-002 prerequisites, capacity and responsibility rules.
import { h, icon, replace, nextId } from '../core/dom.js';
import { get, post, put } from '../core/api.js';
import { href, go } from '../core/router.js';
import { pageHead, panel, chip, timeline, button, busy, confirmDialog, drawer, field, input, notice, toast, skeleton, errorState, empty, pips } from '../core/ui.js';
import { scheduleText, fmtStamp, fmtDateTime, mytDate, mytTimeOf, mytInstant, addDays, minutesText, nights, plural } from '../core/format.js';
import { CHANGEABLE } from '../core/labels.js';
import { staffAssignmentPayload, allocationPayload, decisionPayload } from './payloads.js';
import { runAction } from '../staff/actions.js';
import { workspacePath } from './common.js';

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(10));
  root.append(host);
  let d, ops;
  try { [d, ops] = await Promise.all([get(`/admin/bookings/${encodeURIComponent(ctx.params.id)}/history`), get('/admin/operations')]); }
  catch (e) {
    if (!ctx.alive()) return;
    replace(host, pageHead({ title: 'Booking not found', crumbs: [{ label: 'Bookings', href: href('/bookings') }, { label: 'Not found' }] }),
      e.status === 404 ? h('div', { class: 'panel' }, empty({ icon: 'ban', title: 'This booking does not exist', action: h('a', { class: 'btn btn--secondary', href: href('/bookings') }, 'Back to bookings') })) : errorState(e, ctx.refresh));
    return;
  }
  if (!ctx.alive()) return;
  const b = { ...d.booking, pet_name: d.pet_name, service_name: d.service_name, customer_name: d.customer_name };
  const g = b.booking_type === 'GROOMING';
  const opsRow = ops.needs_decision.find((r) => r.id === b.id);
  const flags = opsRow ? opsRow.flags : [];
  const queue = ops.needs_decision.filter((r) => r.id !== b.id);
  const workload = new Map(ops.staff_work.map((s) => [s.staff_user_id, s.now.length + s.next_7_days.length]));
  const currentUnit = d.accommodation_name || null;
  const currentAlloc = (d.allocation_history || []).find((a) => !a.released_at) || null;
  const staffName = b.assigned_staff_name;
  const reload = () => ctx.refresh();

  const sections = [];
  if (b.status === 'SUBMITTED' || b.status === 'CONFIRMED') sections.push(await preparePanel());
  if (!g && (b.status === 'STAYING' || b.status === 'CHECKED_IN')) sections.push(await handoverPanel());
  const fallback = fallbackPanel();
  if (!ctx.alive()) return;

  const notesList = (d.stay_notes || []).slice().reverse();
  replace(host,
    pageHead({ crumbs: [{ label: 'Bookings', href: href('/bookings') }, { label: `${d.pet_name}, ${d.service_name}` }],
      title: h('span', { class: 'detail-title' }, d.pet_name, chip(b.status)),
      context: [h('span', { class: 'service-mark' }, icon(g ? 'scissors' : 'bed'), d.service_name), h('span', {}, scheduleText(b)), h('span', {}, `Owner: ${d.customer_name}`)],
      actions: queue.length && b.status !== 'SUBMITTED' ? h('a', { class: 'btn btn--secondary', href: href(workspacePath(queue[0])) }, 'Next request', icon('chevron_right')) : null }),
    h('div', { class: 'detail-grid' },
      h('div', { class: 'stack' }, sections, changePanel(), fallback,
        !g ? panel({ title: 'Stay updates', icon: 'note', count: notesList.length, body: notesList.length ? h('div', { class: 'stack stack--sm' }, notesList.map((n) => h('div', { class: 'note-card' }, h('p', {}, n.note), h('div', { class: 'meta' }, fmtStamp(n.created_at)))))
          : empty({ icon: 'note', title: 'No stay updates', compact: true }) }) : null,
        g && d.grooming_record && d.grooming_record.service_notes ? panel({ title: 'Grooming notes', icon: 'note', body: h('div', { class: 'note-card' }, h('p', {}, d.grooming_record.service_notes)) }) : null,
        panel({ title: 'Timeline', icon: 'history', body: timeline(d.timeline) })),
      h('div', { class: 'stack' },
        panel({ title: 'Details', body: h('dl', { class: 'facts' }, [
          ['Owner', d.customer_name], ['Pet', d.pet_name], ['Service', `${d.service_name}${b.grooming_duration_minutes ? `, ${minutesText(b.grooming_duration_minutes)}` : ''}`],
          ['When', scheduleText(b)], ['Team member', staffName || (g ? 'Not assigned' : 'None (optional)')], !g ? ['Accommodation', currentUnit || 'Not allocated'] : null,
          ['Requested', fmtStamp(b.created_at)], ['Reference', b.id.slice(0, 8).toUpperCase()]].filter(Boolean).map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))) }),
        panel({ title: 'Responsibility history', icon: 'users', body: (d.responsibilities || []).length ? h('ol', { class: 'stack stack--sm' }, d.responsibilities.slice().reverse().map((r) => h('li', { class: 'note-card' },
          h('b', {}, r.staff_name), h('div', { class: 'small' }, `${fmtDateTime(r.starts_at)} to ${fmtDateTime(r.effective_end)}`),
          h('div', { class: 'meta' }, [`Assigned by ${r.recorded_by}, ${fmtStamp(r.recorded_at)}`, r.released_at ? `released ${fmtStamp(r.released_at)}` : 'current', r.ended_by ? `ended early by ${r.ended_by}` : null].filter(Boolean).join('; ')))))
          : h('p', { class: 'small muted' }, 'No team member has been assigned.') }),
        !g ? panel({ title: 'Accommodation history', icon: 'bed', body: (d.allocation_history || []).length ? h('ol', { class: 'stack stack--sm' }, d.allocation_history.slice().reverse().map((a) => h('li', { class: 'note-card' },
          h('b', {}, a.name), h('div', { class: 'meta' }, `${a.starts_on} to ${a.ends_on}; allocated ${fmtStamp(a.created_at)}${a.released_at ? `; released ${fmtStamp(a.released_at)}` : '; current'}`))))
          : h('p', { class: 'small muted' }, 'No accommodation allocated yet.') }) : null)));

  // ---------- Prepare and decide ----------
  async function preparePanel() {
    const submitted = b.status === 'SUBMITTED';
    const err = h('div', { hidden: true });
    let staffOptions = [], units = [];
    let pickedStaff = b.assigned_staff_user_id || '';
    let pickedUnit = currentAlloc ? currentAlloc.accommodation_id : '';
    try {
      if (g) staffOptions = await get(`/grooming/bookings/${b.id}/eligible-staff`);
      else {
        [staffOptions, units] = await Promise.all([get('/boarding/staff-options'), post('/admin/boarding-availability', { service_id: b.service_id, boarding_start: b.boarding_start, boarding_end: b.boarding_end })]);
      }
    } catch (e) { return panel({ title: submitted ? 'Review request' : 'Preparation', body: notice('warn', 'Options could not be loaded', e.message) }); }
    if (g && b.assigned_staff_user_id && !staffOptions.some((s) => s.id === b.assigned_staff_user_id)) staffOptions.unshift({ id: b.assigned_staff_user_id, display_name: staffName, current: true });
    const datePassed = flags.includes('date_passed') || (g ? Date.parse(b.grooming_start) <= Date.now() : b.boarding_start < mytDate());
    const staffPicker = h('div', { class: 'picker', role: 'radiogroup', 'aria-label': g ? 'Groomer' : 'Team member (optional)' },
      !g ? radio('staff', '', h('span', {}, h('b', {}, 'No team member'), h('span', { class: 'sub' }, 'Admin handles the stay')), pickedStaff === '', (v) => { pickedStaff = v; }) : null,
      staffOptions.length ? staffOptions.map((s) => radio('staff', s.id, h('div', { class: 'opt-row' }, h('span', {}, h('b', {}, s.display_name || s.email || 'Name not recorded'),
        h('span', { class: 'sub' }, `${workload.get(s.id) || 0} open or upcoming jobs${s.id === b.assigned_staff_user_id ? ', currently assigned' : ''}`))), pickedStaff === s.id, (v) => { pickedStaff = v; }))
        : h('div', { class: 'picker-empty' }, g ? 'No groomer is free for the whole appointment. Reschedule or reject the request.' : 'No active team members.'));
    const unitPicker = !g ? h('div', { class: 'picker', role: 'radiogroup', 'aria-label': 'Accommodation' }, units.length ? units.map((u) => {
      const isCurrent = currentAlloc && currentAlloc.accommodation_id === u.accommodation_id;
      const free = isCurrent ? u.available_places + 1 : u.available_places;
      return radio('unit', u.accommodation_id, h('div', { class: 'opt-row', style: { 'justify-content': 'space-between', width: '100%' } }, h('span', {}, h('b', {}, u.name),
        h('span', { class: 'sub' }, isCurrent ? 'Currently allocated' : free > 0 ? `${plural(free, 'place')} free for the whole stay` : 'Full for part of the stay')),
      pips(u.capacity, u.peak_occupancy, 0, { label: `${u.peak_occupancy} of ${u.capacity} places taken at the busiest night` })), pickedUnit === u.accommodation_id, (v) => { pickedUnit = v; }, !isCurrent && free <= 0);
    }) : h('div', { class: 'picker-empty' }, 'No active accommodation is set up.')) : null;
    const checklist = h('ul', { class: 'checklist' },
      checkItem(!datePassed, datePassed ? 'blocked' : 'ok', g ? 'Appointment is still in the future' : 'Check-in date has not passed',
        datePassed ? 'This request can no longer be confirmed. Reject it, or change its dates first.' : scheduleText(b)),
      g ? checkItem(!!b.assigned_staff_user_id, b.assigned_staff_user_id ? 'ok' : 'missing', 'Groomer assigned', b.assigned_staff_user_id ? staffName : 'Required before confirming. Choose below.')
        : checkItem(!!currentAlloc, currentAlloc ? 'ok' : 'missing', 'Accommodation allocated', currentAlloc ? currentUnit : 'Required before confirming. Choose below.'),
      !g ? checkItem(true, 'ok', 'Team member (optional)', staffName || 'Not assigned; Admin can handle the stay.') : null);
    const confirmBtn = button(submitted ? 'Confirm booking' : 'Save changes', { icon: 'check' });
    const rejectBtn = submitted ? button('Reject request', { variant: 'danger-quiet', icon: 'x_circle' }) : null;
    const saveChanges = async () => {
      if (g && pickedStaff && pickedStaff !== (b.assigned_staff_user_id || '')) await put(`/admin/bookings/${b.id}/staff`, staffAssignmentPayload(b, pickedStaff));
      if (!g && pickedUnit && pickedUnit !== (currentAlloc ? currentAlloc.accommodation_id : '')) await put(`/admin/bookings/${b.id}/accommodation`, allocationPayload(pickedUnit));
      if (!g && pickedStaff !== (b.assigned_staff_user_id || '')) await put(`/admin/bookings/${b.id}/staff`, staffAssignmentPayload(b, pickedStaff || null));
    };
    confirmBtn.addEventListener('click', () => busy(confirmBtn, async () => {
      err.hidden = true;
      if (submitted) {
        if (datePassed) throw new Error('This request can no longer be confirmed because its date has passed.');
        if (g && !pickedStaff) throw new Error('Choose a groomer before confirming.');
        if (!g && !pickedUnit) throw new Error('Choose accommodation before confirming.');
      }
      await saveChanges();
      if (submitted) await post(`/admin/bookings/${b.id}/status`, decisionPayload(true));
      toast(submitted ? `Booking confirmed. ${d.customer_name} has been notified.` : 'Changes saved.');
      if (submitted && queue.length) go(workspacePath(queue[0])); else reload();
    }, { errorTarget: err }));
    if (rejectBtn) rejectBtn.addEventListener('click', async () => {
      const ok = await confirmDialog({ title: 'Reject this request?', danger: true, confirmLabel: 'Reject request', cancelLabel: 'Keep request',
        body: `${d.customer_name} will be told that ${d.pet_name}'s ${d.service_name} request was not accepted. Any prepared groomer or place is released. This cannot be undone.` });
      if (!ok) return;
      const r = await busy(rejectBtn, () => post(`/admin/bookings/${b.id}/status`, decisionPayload(false)), { errorTarget: err });
      if (r) { toast('Request rejected.'); if (queue.length) go(workspacePath(queue[0])); else reload(); }
    });
    return panel({ title: submitted ? 'Review request' : 'Preparation', icon: submitted ? 'clock' : 'settings',
      actions: submitted && queue.length ? h('span', { class: 'small muted' }, `${queue.length} more waiting`) : null,
      body: h('div', { class: 'stack' },
        submitted ? checklist : null,
        h('div', { class: g ? '' : 'grid grid--2' },
          h('section', { class: 'stack stack--sm' }, h('h3', {}, g ? 'Groomer' : 'Team member'), h('p', { class: 'small muted' }, g ? 'Only groomers free for the whole appointment are listed.' : 'Optional. The person is responsible for the whole stay.'), staffPicker),
          !g ? h('section', { class: 'stack stack--sm' }, h('h3', {}, 'Accommodation'), h('p', { class: 'small muted' }, `${plural(nights(b.boarding_start, b.boarding_end), 'night')}; places shown for the busiest night.`), unitPicker) : null),
        err,
        h('div', { class: 'decision-bar' }, h('div', { class: 'row row--wrap' }, confirmBtn,
          submitted ? h('span', { class: 'small muted' }, 'Saves your choices, then confirms and notifies the owner.') : null), rejectBtn)) });
  }

  // ---------- Handover during an active stay ----------
  async function handoverPanel() {
    let options = [];
    try { options = await get('/boarding/staff-options'); } catch (e) { return panel({ title: 'Handover', body: notice('warn', 'Team members could not be loaded', e.message) }); }
    let picked = '';
    const err = h('div', { hidden: true });
    const date = input({ type: 'date', value: mytDate(), min: mytDate(), max: addDays(b.boarding_end, -1) });
    const time = input({ type: 'time', step: 900, value: mytTimeOf(new Date(Date.now() + 5 * 60000).toISOString()) });
    const save = button('Hand over stay', { icon: 'swap' });
    save.addEventListener('click', () => busy(save, async () => {
      if (!picked) throw new Error('Choose who takes over the stay.');
      const when = new Date(mytInstant(date.value, time.value));
      await put(`/admin/bookings/${b.id}/staff`, staffAssignmentPayload(b, picked, when.toISOString()));
      toast('Handover recorded. Both team members have been notified.'); reload();
    }, { errorTarget: err }));
    return panel({ title: 'Handover', icon: 'swap', body: h('div', { class: 'stack' },
      h('p', { class: 'small muted' }, `Currently responsible: ${staffName || 'no team member (Admin)'}. The current person keeps the stay until the handover time; history keeps both.`),
      h('div', { class: 'picker', role: 'radiogroup', 'aria-label': 'Next responsible team member' }, options.filter((s) => s.id !== b.current_staff_user_id).map((s) =>
        radio('handover', s.id, h('span', {}, h('b', {}, s.display_name || s.email), h('span', { class: 'sub' }, `${workload.get(s.id) || 0} open or upcoming jobs`)), false, (v) => { picked = v; }))),
      h('div', { class: 'form-grid form-grid--2' }, field({ label: 'Handover date', input: date }), field({ label: 'Handover time (Malaysia time)', input: time, hint: 'Now or later, before planned check-out.' })),
      err, h('div', { class: 'form-actions' }, save)) });
  }

  // ---------- Change dates / cancel (pre-work only) ----------
  function changePanel() {
    if (!CHANGEABLE.has(b.status)) return null;
    const cancelBtn = button('Cancel booking', { variant: 'danger-quiet', icon: 'ban' });
    cancelBtn.addEventListener('click', async () => {
      const ok = await confirmDialog({ title: 'Cancel this booking?', danger: true, confirmLabel: 'Cancel booking', cancelLabel: 'Keep booking',
        body: `${d.customer_name} will be notified that ${d.pet_name}'s ${d.service_name} is cancelled. Prepared resources are released. This cannot be undone.` });
      if (!ok) return;
      const r = await busy(cancelBtn, () => post(`/admin/bookings/${b.id}/cancel`, {}));
      if (r) { toast('Booking cancelled. The owner has been notified.'); reload(); }
    });
    return panel({ title: 'Change booking', icon: 'calendar', body: h('div', { class: 'stack stack--sm' },
      h('p', { class: 'small muted' }, 'Changing dates returns the booking to Requested and releases the groomer or place until it is confirmed again.'),
      h('div', { class: 'row row--wrap' }, button('Change dates', { variant: 'secondary', icon: 'calendar', onClick: openReschedule }), cancelBtn)) });
  }
  function openReschedule() {
    const { body, close } = drawer({ title: 'Change dates' });
    const err = h('div', { hidden: true });
    const save = button('Save new dates', { type: 'submit' });
    let read, inputs;
    if (g) {
      const dt = input({ type: 'date', value: mytDate(b.grooming_start), min: mytDate() }); const tm = input({ type: 'time', step: 900, value: mytTimeOf(b.grooming_start) });
      inputs = [dt, tm]; read = () => ({ grooming_start: mytInstant(dt.value, tm.value) });
      body.append(h('div', { class: 'form-grid form-grid--2' }, field({ label: 'Date', input: dt }), field({ label: 'Start time (Malaysia time)', input: tm })));
    } else {
      const a = input({ type: 'date', value: b.boarding_start, min: mytDate() }); const z = input({ type: 'date', value: b.boarding_end, min: addDays(b.boarding_start, 1) });
      inputs = [a, z]; read = () => ({ boarding_start: a.value, boarding_end: z.value });
      body.append(h('div', { class: 'form-grid form-grid--2' }, field({ label: 'Check-in date', input: a }), field({ label: 'Check-out date', input: z })));
    }
    const original = JSON.stringify(read());
    const hid = nextId('hint');
    const hint = h('p', { class: 'action-hint', id: hid }, 'Change a date or time to save.');
    const sync = () => { const same = JSON.stringify(read()) === original || inputs.some((i) => !i.value); save.disabled = same; hint.hidden = !same; if (same) save.setAttribute('aria-describedby', hid); else save.removeAttribute('aria-describedby'); };
    inputs.forEach((i) => i.addEventListener('input', sync));
    body.prepend(notice('warn', 'This needs a new decision', 'The booking returns to Requested; the owner is notified and you confirm it again.'));
    body.append(err, h('form', { class: 'form-actions', on: { submit: async (e) => {
      e.preventDefault();
      const r = await busy(save, () => post(`/admin/bookings/${b.id}/reschedule`, read()), { errorTarget: err });
      if (r) { close(); toast('Dates changed. The booking is back in Needs decision.'); reload(); }
    } } }, save, button('Keep current dates', { variant: 'secondary', onClick: close })), hint);
    sync();
  }

  // ---------- Admin fallback fulfilment (approved; disclosed, never the primary path) ----------
  function fallbackPanel() {
    const acts = [];
    const today = mytDate();
    if (g && b.status === 'CONFIRMED') acts.push(['start', 'Start grooming', 'play']);
    if (g && b.status === 'IN_PROGRESS') acts.push(['complete', 'Complete grooming', 'check']);
    if (!g && b.status === 'CONFIRMED' && b.boarding_start <= today && today < b.boarding_end) acts.push(['check-in', 'Check in', 'door_in']);
    if (!g && (b.status === 'STAYING' || b.status === 'CHECKED_IN')) acts.push(['note', 'Add stay update', 'note'], ['check-out', 'Check out', 'door_out']);
    if (!acts.length) return null;
    return h('section', { class: 'panel fallback' }, h('div', { class: 'panel__head' }, h('h2', {}, icon('user'), 'Record on behalf of the team')),
      h('div', { class: 'panel__body stack stack--sm' }, h('p', { class: 'small muted' }, staffName
        ? `${staffName} normally records this. Use these only when they cannot; your name is recorded as the actor.` : 'No team member is responsible, so Admin records the service.'),
      h('div', { class: 'row row--wrap' }, acts.map(([k, label, ic]) => button(label, { variant: 'secondary', icon: ic, onClick: (e) => runAction(k, b, e.currentTarget, reload) })))));
  }
}

function radio(name, value, content, checked, onPick, disabled) {
  const id = nextId('r');
  const r = h('input', { type: 'radio', name, id, value, checked, disabled, on: { change: () => onPick(value) } });
  return h('div', { class: 'option' }, r, h('label', { for: id, style: disabled ? { opacity: '.55', cursor: 'not-allowed' } : null }, content));
}
function checkItem(ok, state, title, text) {
  return h('li', { class: ['check-item', `is-${state}`] }, h('span', { class: 'check-item__mark' }, icon(state === 'ok' ? 'check' : state === 'blocked' ? 'x' : 'alert')),
    h('div', {}, h('b', {}, title), text ? h('p', {}, text) : null));
}
