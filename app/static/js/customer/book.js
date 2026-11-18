// Book a service \u2014 one journey: Service type \u2192 Pet \u2192 Option \u2192 When \u2192 Review. The server re-validates everything.
import { h, icon, replace, nextId } from '../core/dom.js';
import { get, post } from '../core/api.js';
import { go } from '../core/router.js';
import { pageHead, panel, button, busy, field, input, notice, toast, skeleton, errorState, avatar } from '../core/ui.js';
import { mytDate, addDays, mytInstant, fmtDay, fmtTime, minutesText, nights, plural } from '../core/format.js';
import { SERVICE } from '../core/labels.js';
import { detailPath } from './data.js';

const STEPS = ['Type', 'Pet', 'Service', 'Date and time', 'Review'];

export async function render(root, ctx) {
  const host = h('div', {}, skeleton(6));
  root.append(pageHead({ title: 'Book a service' }), host);
  let pets, services;
  try { [pets, services] = await Promise.all([get('/pets'), get('/services')]); }
  catch (e) { if (ctx.alive()) replace(host, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  pets = pets.filter((p) => p.is_active !== false);
  const today = mytDate();
  const s = { type: ['GROOMING', 'BOARDING'].includes(ctx.query.type) ? ctx.query.type : null, petId: pets.some((p) => p.id === ctx.query.pet) ? ctx.query.pet : null,
    serviceId: null, date: today, time: '', start: today, end: addDays(today, 1), check: null, step: 0 };
  if (!s.petId && pets.length === 1) s.petId = pets[0].id;
  s.step = s.type ? (s.petId ? 2 : 1) : 0;
  const options = () => services.filter((x) => x.service_type === s.type);
  const svc = () => services.find((x) => x.id === s.serviceId);
  const pet = () => pets.find((p) => p.id === s.petId);

  const stepsEl = h('ol', { class: 'steps', 'aria-label': 'Booking steps' });
  const stage = h('div', { class: 'step-panel' });
  const summary = h('dl');
  const errorHost = h('div', { hidden: true, role: 'alert' });
  replace(host, h('div', { class: 'wizard' },
    h('div', {}, stepsEl, h('section', { class: 'panel panel__body' }, stage)),
    h('aside', { class: 'summary' }, panel({ title: 'Your request', icon: 'note', body: h('div', { class: 'stack stack--sm' }, summary,
      h('p', { class: 'small muted' }, 'Your time or place is held only after PetOps confirms the request.')) }))));

  const valid = (i) => [!!s.type, !!s.petId, !!s.serviceId, whenValid(), true][i];
  function whenValid() {
    if (s.type === 'GROOMING') return !!(s.date && s.time && new Date(mytInstant(s.date, s.time)) > new Date());
    return !!(s.start && s.end && s.start >= today && s.end > s.start);
  }
  const whenText = () => {
    if (!s.type || !whenValid()) return null;
    if (s.type === 'GROOMING') {
      const startIso = mytInstant(s.date, s.time);
      const end = svc() && svc().duration_minutes ? new Date(Date.parse(startIso) + svc().duration_minutes * 60000) : null;
      return `${fmtDay(s.date)}, ${fmtTime(startIso)}${end ? `\u2013${fmtTime(end)}` : ''}`;
    }
    return `${fmtDay(s.start)} to ${fmtDay(s.end)} (${plural(nights(s.start, s.end), 'night')})`;
  };
  function drawSummary() {
    const row = (label, value) => [h('dt', {}, label), h('dd', {}, value || h('span', { class: 'empty-val' }, 'Not chosen yet'))];
    replace(summary, row('Booking', s.type ? SERVICE[s.type].label : null), row('Pet', pet() && pet().name),
      row('Service', svc() && `${svc().name}${svc().duration_minutes ? `, ${minutesText(svc().duration_minutes)}` : ''}`), row('When', whenText()));
  }
  function drawSteps() {
    replace(stepsEl, STEPS.map((label, i) => h('li', { class: i < s.step ? 'is-done' : i === s.step ? 'is-current' : '', 'aria-current': i === s.step ? 'step' : null },
      h('span', { class: 'n' }, i < s.step ? icon('check') : String(i + 1)),
      i < s.step ? h('button', { type: 'button', class: 'link-btn', style: { color: 'inherit', 'text-decoration': 'none' }, on: { click: () => { s.step = i; draw(); } } }, label) : h('span', {}, label))));
  }
  function radioGroup(name, items, current, onPick, legend) {
    const lid = nextId('lg');
    let pointer = false; // advance automatically on a click/tap, never while arrowing through options with the keyboard
    return h('fieldset', { class: 'options', role: 'radiogroup', 'aria-labelledby': lid, style: { border: '0', padding: '0', margin: '0' },
      on: { pointerdown: () => { pointer = true; }, keydown: () => { pointer = false; } } },
      h('legend', { class: 'visually-hidden', id: lid }, legend),
      items.map((it) => {
        const id = nextId('opt');
        const r = h('input', { type: 'radio', name, id, value: it.value, checked: it.value === current, on: { change: () => onPick(it.value, pointer) } });
        return h('div', { class: 'option' }, r, h('label', { for: id }, it.content));
      }));
  }
  function nav({ nextLabel = 'Continue', onNext } = {}) {
    const back = s.step > 0 ? button('Back', { variant: 'secondary', icon: 'chevron_left', onClick: () => { s.step -= 1; draw(); } }) : h('span');
    const hintId = nextId('hint');
    const next = button(nextLabel, { onClick: onNext || (() => { s.step += 1; draw(); }) });
    if (!valid(s.step)) { next.disabled = true; next.setAttribute('aria-describedby', hintId); }
    return h('div', {}, h('div', { class: 'step-nav' }, back, next),
      !valid(s.step) ? h('p', { class: 'action-hint', id: hintId, style: { 'text-align': 'right' } }, 'Make a choice above to continue.') : null);
  }

  function draw() {
    errorHost.hidden = true;
    drawSteps(); drawSummary();
    if (s.step === 0) {
      replace(stage, h('h2', {}, 'What would you like to book?'),
        radioGroup('type', ['GROOMING', 'BOARDING'].map((t) => ({ value: t, content: h('div', { class: 'opt-row' }, h('span', { class: 'choice__icon' }, icon(SERVICE[t].icon)),
          h('span', {}, h('b', {}, SERVICE[t].label), h('span', { class: 'sub', style: { display: 'block' } }, t === 'GROOMING' ? 'An appointment at a set time' : 'A stay from check-in to check-out'))) })),
        s.type, (v, ptr) => { if (s.type !== v) { s.type = v; s.serviceId = null; s.check = null; } if (ptr) s.step = s.petId ? 2 : 1; draw(); }, 'Service type'), nav());
    } else if (s.step === 1) {
      const addName = input({ maxLength: 120, autocomplete: 'off', placeholder: 'For example, Milo' });
      const addField = field({ label: 'Add another pet', input: addName });
      const addBtn = button('Add pet', { variant: 'secondary', icon: 'plus', type: 'submit' });
      replace(stage, h('h2', {}, 'Who is this for?'),
        pets.length ? radioGroup('pet', pets.map((p) => ({ value: p.id, content: h('div', { class: 'opt-row' }, avatar(p.name), h('b', {}, p.name)) })),
          s.petId, (v, ptr) => { s.petId = v; if (ptr) s.step = 2; draw(); }, 'Pet') : notice('info', 'Add your first pet', 'Bookings are made for a pet. Add one here to continue.'),
        h('form', { class: 'row row--wrap', style: { 'align-items': 'flex-end' }, novalidate: true, on: { submit: async (e) => {
          e.preventDefault(); addField.setError('');
          if (!addName.value.trim()) { addField.setError('Enter your pet\u2019s name.'); return; }
          const created = await busy(addBtn, () => post('/pets', { name: addName.value.trim() }));
          if (created) { pets.push({ ...created, is_active: true }); s.petId = created.id; toast(`${created.name} added.`); draw(); }
        } } }, h('div', { style: { flex: '1', 'min-width': '200px' } }, addField), addBtn), nav());
    } else if (s.step === 2) {
      const list = options();
      if (list.length === 1 && !s.serviceId) s.serviceId = list[0].id;
      replace(stage, h('h2', {}, s.type === 'GROOMING' ? 'Choose a grooming service' : 'Choose a boarding option'),
        list.length ? radioGroup('svc', list.map((x) => ({ value: x.id, content: [h('b', {}, x.name),
          h('span', { class: 'sub' }, x.duration_minutes ? `${minutesText(x.duration_minutes)} appointment` : 'Overnight stay, planned by the night')] })),
        s.serviceId, (v, ptr) => { s.serviceId = v; s.check = null; if (ptr) s.step = 3; draw(); }, 'Service option')
          : notice('warn', 'Not available right now', `No ${SERVICE[s.type].label.toLowerCase()} services are open for booking at the moment.`), nav());
    } else if (s.step === 3) {
      const status = h('div', { 'aria-live': 'polite' });
      const showCheck = () => replace(status, s.check ? notice(s.check.available ? 'ok' : 'warn', s.check.title, s.check.text) : null);
      const resetCheck = () => { s.check = null; showCheck(); drawSummary(); refreshNav(); };
      let fields;
      if (s.type === 'GROOMING') {
        const d = input({ type: 'date', value: s.date, min: today, required: true, on: { input: (e) => { s.date = e.target.value; resetCheck(); } } });
        const t = input({ type: 'time', value: s.time, step: 900, required: true, on: { input: (e) => { s.time = e.target.value; resetCheck(); } } });
        fields = h('div', { class: 'form-grid form-grid--2' }, field({ label: 'Date', input: d }),
          field({ label: 'Start time (Malaysia time)', input: t, hint: svc() && svc().duration_minutes ? `This service takes ${minutesText(svc().duration_minutes)}.` : null }));
      } else {
        const a = input({ type: 'date', value: s.start, min: today, required: true });
        const b = input({ type: 'date', value: s.end, min: addDays(s.start, 1), required: true });
        a.addEventListener('input', () => { s.start = a.value; b.min = addDays(a.value || today, 1); if (s.end <= s.start) { s.end = addDays(s.start, 1); b.value = s.end; } resetCheck(); });
        b.addEventListener('input', () => { s.end = b.value; resetCheck(); });
        fields = h('div', { class: 'form-grid form-grid--2' }, field({ label: 'Check-in date', input: a }),
          field({ label: 'Check-out date', input: b, hint: 'The night before check-out is the last night of the stay.' }));
      }
      const navHost = h('div');
      const refreshNav = () => replace(navHost, nav({ nextLabel: 'Check and continue', onNext: async (ev) => {
        const ok = await busy(ev.currentTarget, checkAvailability);
        showCheck();
        if (ok) { s.step = 4; draw(); }
      } }));
      replace(stage, h('h2', {}, s.type === 'GROOMING' ? 'When should we groom?' : 'When is the stay?'), fields, status, navHost);
      refreshNav(); showCheck();
    } else {
      const submit = button('Request booking', { size: 'lg', icon: 'check' });
      submit.addEventListener('click', () => busy(submit, async () => {
        const body = { pet_id: s.petId, service_id: s.serviceId };
        if (s.type === 'GROOMING') body.grooming_start = mytInstant(s.date, s.time);
        else Object.assign(body, { boarding_start: s.start, boarding_end: s.end });
        try {
          const b = await post('/bookings', body);
          toast('Booking requested. We will confirm it soon.');
          go(detailPath({ ...b, booking_type: s.type }));
        } catch (e) {
          if (e.status === 409 || e.status === 422) { s.check = { available: false, title: 'Please choose another time', text: e.message }; s.step = 3; draw(); return; }
          throw e;
        }
      }, { errorTarget: errorHost }));
      replace(stage, h('h2', {}, 'Review your request'),
        h('dl', { class: 'facts' }, [['Pet', pet().name], ['Service', `${SERVICE[s.type].label}: ${svc().name}`], ['When', whenText()]].map(([k, v]) => h('div', {}, h('dt', {}, k), h('dd', {}, v)))),
        notice('info', 'What happens next', s.type === 'GROOMING'
          ? 'PetOps assigns a groomer and confirms your appointment. You will get a notification when it is confirmed.'
          : 'PetOps reserves a place for the whole stay and confirms it. You will get a notification when it is confirmed.'),
        errorHost,
        h('div', { class: 'step-nav' }, button('Back', { variant: 'secondary', icon: 'chevron_left', onClick: () => { s.step = 3; draw(); } }), submit));
    }
    const heading = stage.querySelector('h2');
    if (heading && ctx.alive() && drawn) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
    drawn = true;
  }
  let drawn = false;

  async function checkAvailability() {
    const body = { service_id: s.serviceId };
    if (s.type === 'GROOMING') body.grooming_start = mytInstant(s.date, s.time);
    else Object.assign(body, { boarding_start: s.start, boarding_end: s.end });
    try {
      const r = await post('/availability', body);
      s.check = r.available
        ? { available: true, title: s.type === 'GROOMING' ? 'A groomer is free for this time' : 'There is space for these dates', text: s.type === 'GROOMING' ? `Ends around ${fmtTime(r.ends_at)}.` : 'Availability is checked again when you send the request.' }
        : { available: false, title: s.type === 'GROOMING' ? 'No groomer is free then' : 'No space for these dates', text: 'Please try another time or dates.' };
    } catch (e) {
      s.check = { available: false, title: 'Please check the details', text: e.message };
    }
    return s.check.available;
  }
  draw();
}
