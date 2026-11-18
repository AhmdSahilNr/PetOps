// Sign in / create account. Registration always creates a Customer account (server rule).
import { h, icon, replace } from '../core/dom.js';
import { signIn, register } from '../core/session.js';
import { button, field, input, notice, busy } from '../core/ui.js';

export function renderAuth(root, onSignedIn) {
  let mode = 'signin';
  const formHost = h('div');
  const tabs = h('div', { class: 'segmented auth__tabs', role: 'tablist', 'aria-label': 'Account' });
  const draw = () => {
    replace(tabs, [['signin', 'Sign in'], ['register', 'Create account']].map(([m, label]) =>
      h('button', { type: 'button', role: 'tab', 'aria-selected': String(mode === m), on: { click: () => { mode = m; draw(); } } }, label)));
    replace(formHost, mode === 'signin' ? signInForm(onSignedIn) : registerForm(onSignedIn));
  };
  draw();
  root.appendChild(h('div', { class: 'auth' },
    h('section', { class: 'auth__story', 'aria-label': 'About PetOps' },
      h('div', { class: 'brand' }, h('span', { class: 'brand__mark' }, icon('paw')), h('span', { class: 'brand__name' }, 'PetOps')),
      h('div', { class: 'auth__pitch' },
        h('p', { class: 'auth__headline' }, 'Grooming and boarding, run from one front desk.'),
        h('ul', { class: 'auth__points' },
          h('li', {}, icon('calendar'), h('span', {}, h('b', {}, 'Pet owners'), ' book grooming or a stay and follow every step.')),
          h('li', {}, icon('list'), h('span', {}, h('b', {}, 'The team'), ' sees exactly the work they are responsible for.')),
          h('li', {}, icon('board'), h('span', {}, h('b', {}, 'Managers'), ' run today, capacity and decisions in one place.')))),
      h('p', { class: 'auth__fine' }, 'Demonstration environment. All people, pets and bookings are fictional.')),
    h('main', { class: 'auth__panel', id: 'main', tabIndex: -1 },
      h('div', { class: 'auth__card' }, h('h1', { tabIndex: -1 }, 'Welcome to PetOps'), h('p', { class: 'muted' }, 'Sign in to manage bookings and work.'), tabs, formHost))));
}

function signInForm(done) {
  const email = input({ type: 'email', name: 'email', autocomplete: 'username', required: true });
  const pw = input({ type: 'password', name: 'password', autocomplete: 'current-password', required: true, maxLength: 128 });
  const err = h('div', { hidden: true });
  const submit = button('Sign in', { type: 'submit', size: 'lg', variant: '' });
  submit.classList.add('btn--block');
  const form = h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
    e.preventDefault(); err.hidden = true;
    if (!email.value.trim() || !pw.value) { replace(err, notice('danger', 'Enter your email and password')); err.hidden = false; return; }
    const ok = await busy(submit, async () => { await signIn(email.value.trim(), pw.value); return true; }, { errorTarget: err });
    if (ok) done();
  } } }, field({ label: 'Email', input: email }), field({ label: 'Password', input: pw }), err, submit);
  return form;
}

function registerForm(done) {
  const name = input({ name: 'display_name', autocomplete: 'name', required: true, maxLength: 120 });
  const email = input({ type: 'email', name: 'email', autocomplete: 'username', required: true });
  const pw = input({ type: 'password', name: 'password', autocomplete: 'new-password', required: true, minLength: 10, maxLength: 128 });
  const fields = { display_name: field({ label: 'Your name', input: name }), email: field({ label: 'Email', input: email }),
    password: field({ label: 'Password', input: pw, hint: 'At least 10 characters.' }) };
  const err = h('div', { hidden: true });
  const submit = button('Create account', { type: 'submit', size: 'lg' });
  submit.classList.add('btn--block');
  return h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
    e.preventDefault(); err.hidden = true;
    Object.values(fields).forEach((f) => f.setError(''));
    let bad = false;
    if (!name.value.trim()) { fields.display_name.setError('Enter your name.'); bad = true; }
    if (!email.value.includes('@')) { fields.email.setError('Enter a valid email address.'); bad = true; }
    if (pw.value.length < 10) { fields.password.setError('Use at least 10 characters.'); bad = true; }
    if (bad) return;
    const ok = await busy(submit, async () => {
      try { await register(name.value.trim(), email.value.trim(), pw.value); return true; }
      catch (ex) { for (const [k, m] of Object.entries(ex.fields || {})) if (fields[k]) fields[k].setError(m); throw ex; }
    }, { errorTarget: err });
    if (ok) done();
  } } }, h('p', { class: 'small muted' }, 'New accounts are for pet owners. Team accounts are created by the business.'),
  fields.display_name, fields.email, fields.password, err, submit);
}
