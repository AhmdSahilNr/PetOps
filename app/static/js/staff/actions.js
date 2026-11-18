// Staff fulfilment actions \u2014 every action calls the canonical endpoint; the server checks responsibility and state.
import { h, nextId } from '../core/dom.js';
import { post } from '../core/api.js';
import { button, busy, confirmDialog, drawer, field, textarea, notice, toast } from '../core/ui.js';

const base = (b) => `/${b.booking_type.toLowerCase()}/bookings/${b.id}`;

export async function runAction(kind, b, btn, after) {
  if (kind === 'start') {
    const r = await busy(btn, () => post(`${base(b)}/start`, {}));
    if (r) { toast(`Grooming started for ${b.pet_name}.`); after(); }
  } else if (kind === 'check-in') {
    const r = await busy(btn, () => post(`${base(b)}/check-in`, {}));
    if (r) { toast(`${b.pet_name} checked in.`); after(); }
  } else if (kind === 'check-out') {
    const ok = await confirmDialog({ title: `Check out ${b.pet_name}?`, confirmLabel: 'Check out', cancelLabel: 'Not yet',
      body: 'This records the departure and completes the stay. The place is released for other bookings. It cannot be undone.' });
    if (!ok) return;
    const r = await busy(btn, () => post(`${base(b)}/check-out`, {}));
    if (r) { toast(`${b.pet_name} checked out. Stay completed.`); after(); }
  } else if (kind === 'complete') {
    openNotes({ title: `Complete grooming for ${b.pet_name}`, label: 'Grooming notes (optional)', submit: 'Complete grooming', optional: true,
      hint: 'Visible to the customer on their booking. For example, what was done and anything to watch.',
      send: (text) => post(`${base(b)}/complete`, text ? { service_notes: text } : {}), done: () => { toast(`Grooming completed for ${b.pet_name}.`); after(); } });
  } else if (kind === 'note') {
    openNotes({ title: `Stay update for ${b.pet_name}`, label: 'Update', submit: 'Add update', optional: false,
      hint: 'Visible to the customer. Describe how the pet is doing.',
      send: (text) => post(`${base(b)}/notes`, { note: text }), done: () => { toast('Stay update added.'); after(); } });
  }
}

function openNotes({ title, label, submit, optional, hint, send, done }) {
  const { body, close } = drawer({ title });
  const ta = textarea({ maxLength: 4000, rows: 6, required: !optional });
  const f = field({ label, input: ta, hint });
  const err = h('div', { hidden: true });
  const save = button(submit, { type: 'submit' });
  body.append(h('form', { class: 'form-grid', novalidate: true, on: { submit: async (e) => {
    e.preventDefault(); f.setError(''); err.hidden = true;
    const text = ta.value.trim();
    if (!optional && !text) { f.setError('Write an update before saving.'); ta.focus(); return; }
    const r = await busy(save, () => send(text), { errorTarget: err });
    if (r) { close(); done(); }
  } } }, f, notice('info', null, 'Recorded with your name and the time.'), err, h('div', { class: 'form-actions' }, save, button('Cancel', { variant: 'secondary', onClick: close }))));
  void nextId;
}
