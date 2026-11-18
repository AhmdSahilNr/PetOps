// My pets \u2014 pet cards with next and last visit; add a pet. No medical or breed fields (not in the approved data model).
import { h, replace, icon } from '../core/dom.js';
import { post } from '../core/api.js';
import { href, go } from '../core/router.js';
import { pageHead, panel, field, input, button, busy, toast, skeleton, errorState, avatar, empty } from '../core/ui.js';
import { relativeDay, bookingDate } from '../core/format.js';
import { loadCustomer, petSummary } from './data.js';

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(5));
  root.append(pageHead({ title: 'My pets' }), host);
  let data;
  try { data = await loadCustomer(); } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const active = data.pets.filter((p) => p.is_active !== false);
  const archived = data.pets.filter((p) => p.is_active === false);
  const name = input({ maxLength: 120, autocomplete: 'off', placeholder: 'For example, Milo' });
  const nameField = field({ label: 'Pet name', input: name });
  const add = button('Add pet', { type: 'submit', icon: 'plus' });
  const card = (p) => {
    const s = petSummary(p, data.bookings);
    return h('a', { class: ['pet-card', p.is_active === false && 'is-archived'], href: href(`/pets/${p.id}`) }, avatar(p.name),
      h('span', {}, h('b', {}, p.name), h('span', { class: 'sub' }, p.is_active === false ? 'Archived'
        : s.next ? `Next: ${s.next.service_name}, ${relativeDay(bookingDate(s.next))}` : s.last ? `Last visit ${relativeDay(bookingDate(s.last))}` : 'No visits yet'),
      h('span', { class: 'sub', style: { display: 'block' } }, `${s.count} booking${s.count === 1 ? '' : 's'}`)));
  };
  replace(host, h('div', { class: 'grid grid--main-rail' },
    h('div', { class: 'stack' },
      active.length ? h('div', { class: 'pet-cards' }, active.map(card))
        : h('div', { class: 'panel' }, empty({ icon: 'paw', title: 'No pets yet', text: 'Add your pet to start booking grooming or a stay.' })),
      archived.length ? h('section', {}, h('div', { class: 'section-title' }, h('h2', {}, 'Archived pets')), h('div', { class: 'pet-cards' }, archived.map(card))) : null),
    panel({ title: 'Add a pet', icon: 'plus', body: h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
      e.preventDefault(); nameField.setError('');
      if (!name.value.trim()) { nameField.setError('Enter your pet\u2019s name.'); name.focus(); return; }
      const created = await busy(add, () => post('/pets', { name: name.value.trim() }));
      if (created) { toast(`${created.name} added.`); go(`/pets/${created.id}`); }
    } } }, nameField, h('div', { class: 'form-actions' }, add)) })));
  if (ctx.query.add) name.focus();
  void icon;
}
