// Profile (account controls kept apart from operational pages). Customer and Staff can edit their display name;
// Staff can also change their own password (supervisor correction, Nov 2026). Admin cannot change it for them.
import { h, replace } from '../core/dom.js';
import { get, put } from '../core/api.js';
import { pageHead, panel, field, input, button, busy, toast, skeleton, errorState, avatar, showError } from '../core/ui.js';
import { session } from '../core/session.js';

function passwordPanel() {
  const current = input({ type: 'password', name: 'current_password', autocomplete: 'current-password', required: true, maxLength: 128 });
  const next = input({ type: 'password', name: 'new_password', autocomplete: 'new-password', required: true, minLength: 10, maxLength: 128 });
  const again = input({ type: 'password', name: 'confirm_password', autocomplete: 'new-password', required: true, minLength: 10, maxLength: 128 });
  const f = {
    current: field({ label: 'Current password', input: current }),
    next: field({ label: 'New password', input: next, hint: 'At least 10 characters, different from your current password.' }),
    again: field({ label: 'Confirm new password', input: again }),
  };
  const err = h('div', { hidden: true, 'aria-live': 'polite' });
  const save = button('Change password', { type: 'submit', icon: 'key' });
  const form = h('form', { class: 'form-grid', novalidate: true, 'aria-label': 'Change password', on: { submit: async (e) => {
    e.preventDefault(); err.hidden = true; Object.values(f).forEach((x) => x.setError(''));
    let first = null;
    const fail = (key, msg, el) => { f[key].setError(msg); first = first || el; };
    if (!current.value) fail('current', 'Enter your current password.', current);
    if (next.value.length < 10) fail('next', 'Use at least 10 characters.', next);
    else if (next.value.length > 128) fail('next', 'Use 128 characters or fewer.', next);
    else if (next.value === current.value) fail('next', 'Choose a password different from your current one.', next);
    if (!first && again.value !== next.value) fail('again', 'The two new passwords do not match.', again);
    if (first) { first.focus(); return; }
    const done = await busy(save, async () => {
      try {
        await put('/account/password', { current_password: current.value, new_password: next.value });
        return true;
      } catch (ex) {
        if (ex.status === 400) { fail('current', 'Your current password is incorrect.', current); current.focus(); return false; }
        if (ex.fields && ex.fields.new_password) { fail('next', ex.fields.new_password, next); next.focus(); return false; }
        throw ex;
      }
    }, { errorTarget: err });
    if (done) {
      current.value = ''; next.value = ''; again.value = '';
      toast('Password changed. Any other signed-in devices have been signed out.');
    }
  } } }, f.current, f.next, f.again, err, h('div', { class: 'form-actions' }, save));
  return panel({ title: 'Password', icon: 'key', body: h('div', { class: 'stack stack--sm' },
    h('p', { class: 'small muted' }, 'Your password is private: Admin cannot see or change it. If you forget it, it cannot be reset in this version of PetOps.'), form) });
}

export async function render(root, ctx) {
  const isCustomer = ctx.user.role === 'CUSTOMER';
  const isStaff = ctx.user.role === 'STAFF';
  const host = h('div', {}, skeleton(3));
  root.append(pageHead({ title: 'Profile' }), host);
  try {
    const profile = isCustomer ? await get('/customer/profile') : { display_name: ctx.user.display_name, email: ctx.user.email };
    if (!ctx.alive()) return;
    const name = input({ value: profile.display_name || '', maxLength: 120, autocomplete: 'name', required: true });
    const nameField = field({ label: 'Display name', input: name, hint: isCustomer ? 'Shown to the PetOps team on your bookings.' : 'Shown to Admin on your assignments.' });
    const save = button('Save changes', { type: 'submit' });
    const details = panel({ title: 'Your details', body: h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
      e.preventDefault(); nameField.setError('');
      if (!name.value.trim()) { nameField.setError('Enter a name.'); name.focus(); return; }
      await busy(save, async () => {
        const r = await put(isCustomer ? '/customer/profile' : '/account', { display_name: name.value.trim() });
        session.user = { ...session.user, display_name: r.display_name };
        toast('Profile saved.');
      });
    } } }, nameField,
    h('div', { class: 'field' }, h('span', { class: 'label' }, 'Email'), h('p', {}, profile.email), h('span', { class: 'hint' }, 'Your sign-in email cannot be changed here.')),
    h('div', { class: 'form-actions' }, save)) });
    replace(host, h('div', { class: 'grid grid--main-rail' },
      h('div', { class: 'stack' }, details, isStaff ? passwordPanel() : null),
      panel({ title: 'Account', body: h('div', { class: 'stack stack--sm' }, h('div', { class: 'row' }, avatar(profile.display_name || profile.email),
        h('div', {}, h('div', { class: 'strong' }, profile.display_name || 'Name not set'), h('div', { class: 'small muted' }, isCustomer ? 'Pet owner account' : 'Team account'))),
      h('p', { class: 'small muted' }, isCustomer ? 'Manage your pets on the Pets page.' : 'Your assigned work is on My work. Account status is managed by Admin.')) })));
  } catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); }
}
