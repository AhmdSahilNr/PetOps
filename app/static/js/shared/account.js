// Profile (account controls kept apart from operational pages). Customer and Staff can edit their display name.
import { h, replace } from '../core/dom.js';
import { get, put } from '../core/api.js';
import { pageHead, panel, field, input, button, busy, toast, skeleton, errorState, avatar } from '../core/ui.js';
import { session } from '../core/session.js';

export async function render(root, ctx) {
  const isCustomer = ctx.user.role === 'CUSTOMER';
  const host = h('div', {}, skeleton(3));
  root.append(pageHead({ title: 'Profile' }), host);
  try {
    const profile = isCustomer ? await get('/customer/profile') : { display_name: ctx.user.display_name, email: ctx.user.email };
    if (!ctx.alive()) return;
    const name = input({ value: profile.display_name || '', maxLength: 120, autocomplete: 'name', required: true });
    const nameField = field({ label: 'Display name', input: name, hint: isCustomer ? 'Shown to the PetOps team on your bookings.' : 'Shown to Admin on your assignments.' });
    const save = button('Save changes', { type: 'submit' });
    replace(host, h('div', { class: 'grid grid--main-rail' },
      panel({ title: 'Your details', body: h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
        e.preventDefault(); nameField.setError('');
        if (!name.value.trim()) { nameField.setError('Enter a name.'); name.focus(); return; }
        await busy(save, async () => {
          const r = await put(isCustomer ? '/customer/profile' : '/account', { display_name: name.value.trim() });
          session.user = { ...session.user, display_name: r.display_name };
          toast('Profile saved.');
        });
      } } }, nameField,
      h('div', { class: 'field' }, h('span', { class: 'label' }, 'Email'), h('p', {}, profile.email), h('span', { class: 'hint' }, 'Your sign-in email cannot be changed here.')),
      h('div', { class: 'form-actions' }, save)) }),
      panel({ title: 'Account', body: h('div', { class: 'stack stack--sm' }, h('div', { class: 'row' }, avatar(profile.display_name || profile.email),
        h('div', {}, h('div', { class: 'strong' }, profile.display_name || 'Name not set'), h('div', { class: 'small muted' }, isCustomer ? 'Pet owner account' : 'Team account'))),
      h('p', { class: 'small muted' }, isCustomer ? 'Manage your pets on the Pets page.' : 'Your assigned work is on My work. Account status is managed by Admin.')) })));
  } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); }
}
