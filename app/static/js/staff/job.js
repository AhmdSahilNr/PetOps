// Staff job page \u2014 Grooming appointment or Boarding stay, with the one next action first.
import { h, icon, replace } from '../core/dom.js';
import { get } from '../core/api.js';
import { href } from '../core/router.js';
import { pageHead, panel, chip, timeline, button, skeleton, errorState, empty, notice, meter, flagTag } from '../core/ui.js';
import { isOverdueStay } from '../core/labels.js';
import { scheduleText, fmtStamp, fmtDateTime, mytDate, nights, daysBetween, fmtDay, minutesText } from '../core/format.js';
import { staffNextAction, staffSection } from './queue.js';
import { runAction } from './actions.js';

export async function render(root, ctx) {
  const type = ctx.params.type === 'boarding' ? 'boarding' : 'grooming';
  const host = h('div', {}, skeleton(8));
  root.append(host);
  let d;
  try { d = await get(`/${type}/bookings/${encodeURIComponent(ctx.params.id)}`); }
  catch (e) {
    if (!ctx.alive()) return;
    replace(host, pageHead({ title: 'Work not available', crumbs: [{ label: 'My work', href: href('/work') }, { label: 'Not available' }] }),
      e.status === 404 ? h('div', { class: 'panel' }, empty({ icon: 'ban', title: 'This work is not assigned to you',
        text: 'It may have been reassigned, cancelled or completed by someone else. Your current work is on My work.',
        action: h('a', { class: 'btn btn--secondary', href: href('/work') }, 'Back to My work') })) : errorState(e, ctx.refresh));
    return;
  }
  if (!ctx.alive()) return;
  const me = ctx.user.id;
  const b = { ...d.booking, pet_name: d.pet_name, service_name: d.service_name, customer_name: d.customer_name, accommodation_name: d.accommodation_name };
  const g = b.booking_type === 'GROOMING';
  const next = staffNextAction(b, me);
  const after = () => ctx.refresh();
  const later = staffSection(b, me) === 'upcoming'; // QA F-15: allowed early, but not presented as the primary action
  const mkPrimary = () => next.action ? button(later && g ? `${next.label} early` : next.label, { variant: later ? 'secondary' : '', icon: { start: 'play', complete: 'check', 'check-in': 'door_in', note: 'note' }[next.action], onClick: (e) => runAction(next.action, b, e.currentTarget, after) }) : null;
  const mkSecondary = () => next.secondary ? button(next.secondary.label, { variant: 'secondary', icon: 'door_out', onClick: (e) => runAction(next.secondary.action, b, e.currentTarget, after) }) : null;
  const mine = (d.responsibilities || []).filter((r) => r.staff_user_id === me && !r.released_at);
  const today = mytDate();
  let progress = null;
  if (!g && (b.status === 'STAYING' || b.status === 'CHECKED_IN')) {
    const total = nights(b.boarding_start, b.boarding_end); const done = Math.min(total, Math.max(0, daysBetween(b.boarding_start, today)));
    progress = h('div', { class: 'stay-progress' }, h('div', { class: 'row row--between' }, h('b', {}, `Night ${Math.min(done + 1, total)} of ${total}`),
      isOverdueStay(b, today) ? flagTag('past_planned_checkout') : null),
    meter(done + 1, total, 'care'), h('div', { class: 'stay-progress__ends' }, h('span', {}, `Check-in ${fmtDay(b.boarding_start)}`), h('span', {}, `Check-out ${fmtDay(b.boarding_end)}`)));
  }
  const notes = (d.stay_notes || []).slice().reverse();
  replace(host,
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('a', { href: href('/work') }, 'My work'), icon('chevron_right'), h('span', { 'aria-current': 'page' }, `${d.pet_name}, ${d.service_name}`)),
    h('header', { class: 'job-head' }, h('span', { class: 'job-head__icon' }, icon(g ? 'scissors' : 'bed')),
      h('div', {}, h('h1', { tabIndex: -1 }, d.pet_name), h('div', { class: 'job-head__sub' }, chip(b.status), h('span', {}, d.service_name), h('span', {}, scheduleText(b)))),
      h('div', { class: 'page-head__actions' }, mkPrimary(), mkSecondary())),
    h('div', { class: ['detail-grid', (next.action) && 'has-sticky'] },
      h('div', { class: 'stack' },
        panel({ title: 'What to do', icon: 'list', body: h('div', { class: 'stack stack--sm' },
          progress,
          next.action ? notice('info', next.label, {
            start: 'Start when the pet is with you. The start time is recorded with your name.',
            complete: 'Finish with optional notes for the customer. Completion releases the appointment.',
            'check-in': 'Record the arrival when the pet is handed over. Check-in is possible during the reserved dates only.',
            note: 'Add updates during the stay. Check out when the pet goes home; that also completes the stay.' }[next.action])
            : notice(b.status === 'COMPLETED' ? 'ok' : 'info', next.reason || (b.status === 'COMPLETED' ? 'Completed' : 'No action needed'),
              next.startsAt ? `From ${fmtDateTime(next.startsAt)}.` : b.status === 'COMPLETED' ? 'This work is finished and kept in your history.' : '')) }),
        !g ? panel({ title: 'Stay updates', icon: 'note', count: notes.length, body: notes.length ? h('div', { class: 'stack stack--sm' }, notes.map((n) => h('div', { class: 'note-card' }, h('p', {}, n.note), h('div', { class: 'meta' }, fmtStamp(n.created_at)))))
          : empty({ icon: 'note', title: 'No stay updates yet', text: 'Updates you add are shown to the customer.', compact: true }) }) : null,
        g && d.grooming_record && d.grooming_record.service_notes ? panel({ title: 'Grooming notes', icon: 'note', body: h('div', { class: 'note-card' }, h('p', {}, d.grooming_record.service_notes)) }) : null,
        panel({ title: 'Activity', icon: 'history', body: timeline(d.timeline) })),
      h('div', { class: 'stack' },
        panel({ title: 'Details', body: h('dl', { class: 'facts' }, [
          ['Pet', d.pet_name], ['Owner', d.customer_name], ['Service', `${d.service_name}${b.grooming_duration_minutes ? `, ${minutesText(b.grooming_duration_minutes)}` : ''}`],
          ['When', scheduleText(b)], !g ? ['Accommodation', d.accommodation_name || 'Released after check-out'] : null,
          d.grooming_record && d.grooming_record.started_at ? ['Started', fmtStamp(d.grooming_record.started_at)] : null,
          d.grooming_record && d.grooming_record.completed_at ? ['Completed', fmtStamp(d.grooming_record.completed_at)] : null,
        ].filter(Boolean).map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))) }),
        panel({ title: 'Your responsibility', icon: 'user', body: mine.length ? h('ul', { class: 'stack stack--sm' }, mine.map((r) => h('li', {}, h('b', {}, `${fmtDateTime(r.starts_at)} to ${fmtDateTime(r.effective_end)}`),
          h('div', { class: 'small muted' }, `Assigned by ${r.recorded_by}`)))) : h('p', { class: 'small muted' }, 'You were the last responsible team member for this work.') }))),
    next.action ? h('div', { class: 'sticky-actions' }, mkPrimary(), mkSecondary()) : null);
}
