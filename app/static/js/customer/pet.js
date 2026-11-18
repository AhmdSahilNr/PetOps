// Pet page \u2014 identity, next visit, last completed service, Grooming and Boarding history, manage.
import { h, replace } from '../core/dom.js';
import { put, post, api } from '../core/api.js';
import { href, go } from '../core/router.js';
import { pageHead, panel, field, input, button, busy, toast, confirmDialog, skeleton, errorState, avatar, empty, notice } from '../core/ui.js';
import { scheduleText } from '../core/format.js';
import { loadCustomer, petSummary } from './data.js';
import { bookingRow, spotlightCard } from './common.js';

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(6));
  root.append(host);
  let data;
  try { data = await loadCustomer(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const pet = data.pets.find((p) => p.id === ctx.params.id);
  if (!pet) {
    replace(host, pageHead({ title: 'Pet not found', crumbs: [{ label: 'My pets', href: href('/pets') }, { label: 'Not found' }] }),
      h('div', { class: 'panel' }, empty({ icon: 'paw', title: 'This pet is not on your account', action: h('a', { class: 'btn btn--secondary', href: href('/pets') }, 'Back to my pets') })));
    return;
  }
  const archived = pet.is_active === false;
  const s = petSummary(pet, data.bookings);
  const grooming = s.bookings.filter((b) => b.booking_type === 'GROOMING').reverse();
  const boarding = s.bookings.filter((b) => b.booking_type === 'BOARDING').reverse();
  const name = input({ value: pet.name, maxLength: 120, required: true });
  const nameField = field({ label: 'Name', input: name });
  const save = button('Save name', { type: 'submit', variant: 'secondary' });
  const history = (title, ic, list, emptyText) => panel({ title, icon: ic, count: list.length, flush: true,
    body: list.length ? h('div', { class: 'rows' }, list.map(bookingRow)) : empty({ icon: ic, title: `No ${title.toLowerCase()} yet`, text: emptyText, compact: true }) });
  replace(host,
    pageHead({ crumbs: [{ label: 'My pets', href: href('/pets') }, { label: pet.name }],
      title: h('span', { class: 'row' }, avatar(pet.name, 'avatar--lg'), h('span', {}, pet.name)),
      context: archived ? 'Archived. History is kept; new bookings are not possible.' : `${s.count} booking${s.count === 1 ? '' : 's'} so far`,
      actions: archived ? null : h('a', { class: 'btn', href: href('/book', { pet: pet.id }) }, `Book for ${pet.name}`) }),
    h('div', { class: 'detail-grid' },
      h('div', { class: 'stack' },
        s.next ? h('section', {}, h('div', { class: 'section-title' }, h('h2', {}, 'Next visit')), spotlightCard({ ...s.next })) : null,
        history('Grooming history', 'scissors', grooming, 'Grooming appointments for this pet will be listed here.'),
        history('Boarding history', 'bed', boarding, 'Boarding stays for this pet will be listed here.')),
      h('div', { class: 'stack' },
        panel({ title: 'At a glance', body: h('dl', { class: 'facts' },
          [['Next visit', s.next ? scheduleText(s.next) : 'None booked'], ['Last completed', s.last ? `${s.last.service_name}, ${scheduleText(s.last)}` : 'Nothing yet'],
            ['Grooming visits', String(grooming.length)], ['Boarding stays', String(boarding.length)]].map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))) }),
        archived ? notice('info', 'Archived pet', 'Archived pets stay in your history but cannot be booked.') : panel({ title: 'Manage', body: h('div', { class: 'stack' },
          h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
            e.preventDefault(); nameField.setError('');
            if (!name.value.trim()) { nameField.setError('Enter a name.'); return; }
            const r = await busy(save, () => put(`/pets/${pet.id}`, { name: name.value.trim() }));
            if (r) { toast('Name saved.'); ctx.refresh(); }
          } } }, nameField, h('div', { class: 'form-actions' }, save)),
          h('div', { class: 'stack stack--sm' }, h('p', { class: 'small muted' }, s.count
            ? 'Archiving keeps this pet\u2019s history but stops new bookings.' : 'This pet has no bookings, so it can be removed completely.'),
          button(s.count ? 'Archive pet' : 'Remove pet', { variant: 'danger-quiet', icon: s.count ? 'archive' : 'x', onClick: (e) => manage(e.currentTarget, pet, s.count) }))) }))));
}

async function manage(btn, pet, count) {
  const ok = await confirmDialog({ danger: true, title: count ? `Archive ${pet.name}?` : `Remove ${pet.name}?`,
    confirmLabel: count ? 'Archive pet' : 'Remove pet', cancelLabel: 'Keep pet',
    body: count ? `${pet.name} will no longer be available for new bookings. Past and current bookings stay in your history. Archiving cannot be undone online.`
      : `${pet.name} will be removed from your account. This cannot be undone.` });
  if (!ok) return;
  const r = await busy(btn, () => (count ? post(`/pets/${pet.id}/archive`) : api(`/pets/${pet.id}`, { method: 'DELETE' }).then(() => true)));
  if (r) { toast(count ? `${pet.name} archived.` : `${pet.name} removed.`); go('/pets'); }
}
