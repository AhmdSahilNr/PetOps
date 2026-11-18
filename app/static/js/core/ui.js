// Shared UI components. Every component renders text only and is keyboard accessible.
import { h, icon, nextId, replace } from './dom.js';
import { STATUS, SERVICE, FLAG, trackerSteps } from './labels.js';
import { initials, fmtStamp } from './format.js';

export function pageHead({ title, context, actions, crumbs }) {
  return h('header', { class: 'page-head' },
    h('div', { class: 'page-head__text' },
      crumbs && crumbs.length ? h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' },
        crumbs.map((c, i) => [i ? icon('chevron_right') : null, c.href ? h('a', { href: c.href }, c.label) : h('span', { 'aria-current': 'page' }, c.label)])) : null,
      h('h1', { tabIndex: -1, class: 'page-title' }, title),
      context ? h('div', { class: 'page-head__context' }, context) : null),
    actions ? h('div', { class: 'page-head__actions' }, actions) : null);
}

export function chip(status) {
  const s = STATUS[status] || { label: status, tone: 'cancelled', icon: 'info' };
  return h('span', { class: `chip chip--${s.tone}` }, icon(s.icon), s.label);
}
export function flagTag(flag) {
  const f = FLAG[flag];
  if (!f) return null;
  return h('span', { class: `tag tag--${f.tone}`, title: f.hint || null }, icon(f.icon), f.label, f.hint ? h('span', { class: 'visually-hidden' }, `: ${f.hint}`) : null);
}
export function serviceMark(type, name) {
  const s = SERVICE[type] || SERVICE.GROOMING;
  return h('span', { class: 'service-mark' }, icon(s.icon), name || s.label);
}
export function avatar(name, variant = '') { return h('span', { class: `avatar ${variant}`, 'aria-hidden': 'true' }, initials(name)); }

export function button(label, { icon: ic, variant = '', size = '', onClick, type = 'button', href, disabled, describedBy, ariaLabel } = {}) {
  const cls = ['btn', variant && `btn--${variant}`, size && `btn--${size}`, !label && 'btn--icon'];
  if (href) return h('a', { class: cls, href, 'aria-label': ariaLabel }, ic ? icon(ic) : null, label);
  return h('button', { class: cls, type, disabled, 'aria-describedby': describedBy, 'aria-label': ariaLabel, on: onClick ? { click: onClick } : undefined }, ic ? icon(ic) : null, label);
}

/** Run an async action with a busy button; returns the action result or undefined on error (error is toasted). */
export async function busy(btn, fn, { errorTarget } = {}) {
  if (btn.disabled) return undefined;
  btn.disabled = true; btn.classList.add('is-busy'); btn.setAttribute('aria-busy', 'true');
  try { return await fn(); }
  catch (e) {
    if (errorTarget) showError(errorTarget, e); else toast(e.message || 'Something did not complete. Try again.', 'error');
    return undefined;
  } finally { btn.disabled = false; btn.classList.remove('is-busy'); btn.removeAttribute('aria-busy'); }
}

export function empty({ icon: ic = 'info', title, text, action, compact }) {
  return h('div', { class: ['empty', compact && 'empty--compact'] },
    h('div', { class: 'empty__icon' }, icon(ic)), h('h3', {}, title), text ? h('p', {}, text) : null, action || null);
}
export function skeleton(lines = 4) { return h('div', { class: 'skeleton', role: 'status', 'aria-label': 'Loading' }, Array.from({ length: lines }, () => h('i'))); }
export function errorState(err, retry) {
  return h('div', { class: 'notice notice--danger', role: 'alert' }, icon('alert'),
    h('div', {}, h('strong', {}, 'This could not be loaded'), h('span', {}, err && err.message ? err.message : 'Try again.'),
      retry ? h('div', { style: { 'margin-top': '8px' } }, button('Try again', { variant: 'secondary', size: 'sm', icon: 'refresh', onClick: retry })) : null));
}
export function notice(kind, title, text, ic) {
  const icons = { info: 'info', warn: 'alert', danger: 'alert', ok: 'check_circle' };
  return h('div', { class: `notice notice--${kind}`, role: kind === 'danger' ? 'alert' : null }, icon(ic || icons[kind] || 'info'),
    h('div', {}, title ? h('strong', {}, title) : null, text ? h('span', {}, text) : null));
}
export function showError(target, e) {
  replace(target, notice('danger', 'Not saved', e.message || 'Try again.'));
  target.hidden = false;
}

export function toast(message, kind = 'ok') {
  const region = document.getElementById('toasts');
  const t = h('div', { class: `toast toast--${kind}` }, icon(kind === 'error' ? 'alert' : 'check_circle'), h('span', {}, message));
  region.appendChild(t);
  setTimeout(() => t.remove(), kind === 'error' ? 7000 : 4000);
}

export function panel({ title, icon: ic, count, actions, body, foot, flush, className, headingLevel = 'h2', id }) {
  return h('section', { class: ['panel', className], 'aria-labelledby': id || null },
    title ? h('div', { class: 'panel__head' }, h(headingLevel, { id: id || null }, ic ? icon(ic) : null, title, count !== undefined && count !== null ? h('span', { class: 'count' }, String(count)) : null), actions || null) : null,
    h('div', { class: ['panel__body', flush && 'panel__body--flush'] }, body),
    foot ? h('div', { class: 'panel__foot' }, foot) : null);
}

export function kpi({ label, icon: ic, value, unit, meaning, onClick, alert, delta, ariaLabel }) {
  const content = [h('span', { class: 'kpi__label' }, ic ? icon(ic) : null, label),
    h('span', { class: 'kpi__value' }, value === null || value === undefined ? '\u2014' : String(value), unit ? h('small', {}, ` ${unit}`) : null),
    meaning ? h('span', { class: 'kpi__meaning' }, meaning) : null, delta || null];
  if (onClick) return h('button', { type: 'button', class: ['kpi', alert && 'kpi--alert'], on: { click: onClick }, 'aria-label': ariaLabel || null }, content, icon('chevron_right', { className: 'kpi__go' }));
  return h('div', { class: ['kpi', alert && 'kpi--alert'] }, content);
}

export function deltaChip(change, { goodWhenUp = true, unit = '' } = {}) {
  if (!change) return null;
  const { diff, pct } = change;
  if (diff === 0) return h('span', { class: 'delta' }, 'Same as previous period');
  const up = diff > 0;
  const text = pct !== null ? `${up ? '+' : ''}${pct}% vs previous` : `${up ? '+' : ''}${diff}${unit} vs previous`;
  return h('span', { class: 'delta', title: goodWhenUp === null ? null : undefined }, icon(up ? 'arrow_up' : 'arrow_down'), text);
}

export function segmented(options, current, onChange, label) {
  return h('div', { class: 'segmented', role: 'group', 'aria-label': label },
    options.map((o) => h('button', { type: 'button', 'aria-pressed': String(o.value === current), on: { click: () => onChange(o.value) } },
      o.icon ? icon(o.icon) : null, o.label, o.count !== undefined ? h('span', { class: 'n' }, String(o.count)) : null)));
}

export function field({ label, input, hint, error, id }) {
  const fid = id || input.id || nextId('f');
  input.id = fid;
  const hintId = hint ? `${fid}-hint` : null;
  const errId = `${fid}-err`;
  const err = h('div', { class: 'field-error', id: errId, hidden: !error }, icon('alert'), h('span', {}, error || ''));
  input.setAttribute('aria-describedby', [hintId, errId].filter(Boolean).join(' '));
  if (error) input.setAttribute('aria-invalid', 'true');
  const wrap = h('div', { class: 'field' }, h('label', { for: fid }, label), hint ? h('div', { class: 'hint', id: hintId }, hint) : null, input, err);
  wrap.setError = (msg) => {
    err.hidden = !msg; err.lastChild.textContent = msg || '';
    if (msg) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
  };
  return wrap;
}
export const input = (props) => h('input', { class: 'input', ...props });
export const select = (options, props = {}) => h('select', { class: 'select', ...props },
  options.map((o) => h('option', { value: o.value, selected: o.selected || o.value === props.value, disabled: o.disabled }, o.label)));
export const textarea = (props) => h('textarea', { class: 'textarea', ...props });

/** Place pips: one pip per configured place. held = reserved places; here = physically in care. */
export function pips(capacity, held = 0, here = 0, { large, label, requested = 0 } = {}) {
  const items = [];
  // Order: in care, then requested-with-place-held, then other confirmed reservations, then free places.
  for (let i = 0; i < capacity; i += 1) items.push(h('i', { class: ['pip', i < here ? 'pip--here' : i < here + requested ? 'pip--req' : i < held ? 'pip--held' : null] }));
  return h('span', { class: ['pips', large && 'pips--lg'], role: 'img', 'aria-label': label || `${held} of ${capacity} places taken` }, items,
    h('span', { class: 'pips__label', 'aria-hidden': 'true' }, `${held}/${capacity}`));
}

export function meter(value, max, variant = '') {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  const fill = h('i');
  fill.style.width = `${pct}%`;
  return h('div', { class: ['meter', variant && `meter--${variant}`], role: 'meter', 'aria-valuemin': '0', 'aria-valuemax': String(max), 'aria-valuenow': String(value) }, fill);
}

export function tracker(b) {
  const steps = trackerSteps(b);
  return h('ol', { class: 'tracker', 'aria-label': 'Booking progress' }, steps.map((s) => h('li', {
    class: ['tracker__step', `is-${s.state}`], 'aria-current': s.state === 'current' ? 'step' : null },
  h('span', { class: 'tracker__dot' }, icon(s.state === 'done' ? 'check' : s.icon)), h('span', {}, s.label))));
}

export function timeline(entries, { emptyText = 'No activity has been recorded yet.' } = {}) {
  if (!entries || !entries.length) return empty({ icon: 'history', title: 'No activity yet', text: emptyText, compact: true });
  return h('ol', { class: 'timeline' }, [...entries].reverse().map((e) => h('li', { class: ['tl', e.tone && `tl--${e.tone}`] },
    h('span', { class: 'tl__title' }, e.title),
    h('span', { class: 'tl__meta' }, [fmtStamp(e.at), e.actor ? `by ${e.actor}${e.actor_role && e.actor_role !== 'Customer' ? ` (${e.actor_role})` : ''}` : null].filter(Boolean).join(', ')),
    e.body ? h('span', { class: 'tl__body' }, e.body) : null)));
}

// ---------- Overlays with focus management ----------
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
function trap(overlay, box, onClose) {
  const opener = document.activeElement;
  const keydown = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    if (e.key !== 'Tab') return;
    const f = [...box.querySelectorAll(FOCUSABLE)].filter((x) => x.offsetParent !== null);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  };
  overlay.addEventListener('keydown', keydown);
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) onClose(); });
  document.body.appendChild(overlay);
  document.body.style.setProperty('overflow', 'hidden');
  requestAnimationFrame(() => { const first = box.querySelector('[data-autofocus]') || box.querySelector(FOCUSABLE); (first || box).focus(); });
  return () => { overlay.remove(); document.body.style.removeProperty('overflow'); if (opener && opener.focus) opener.focus(); };
}

/** Confirmation for destructive / significant actions only (directive 03 \u00a728). Resolves true/false. */
export function confirmDialog({ title, body, confirmLabel, cancelLabel = 'Keep it as it is', danger = false }) {
  return new Promise((resolve) => {
    const tid = nextId('dlg');
    let closeFn;
    const done = (v) => { closeFn(); resolve(v); };
    const box = h('div', { class: 'dialog', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': tid, tabIndex: -1 },
      h('h2', { id: tid }, title), h('p', { class: 'muted' }, body),
      h('div', { class: 'dialog__actions' },
        button(cancelLabel, { variant: 'secondary', onClick: () => done(false) }),
        h('button', { class: ['btn', danger && 'btn--danger'], type: 'button', 'data-autofocus': '', on: { click: () => done(true) } }, confirmLabel)));
    const overlay = h('div', { class: 'overlay' }, box);
    closeFn = trap(overlay, box, () => done(false));
  });
}

/** Side drawer for short focused tasks. Returns { body, close }. */
export function drawer({ title, onClose }) {
  const tid = nextId('drw');
  const body = h('div', { class: 'drawer__body' });
  let closeFn;
  const close = () => { closeFn(); if (onClose) onClose(); };
  const box = h('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': tid, tabIndex: -1 },
    h('div', { class: 'drawer__head' }, h('h2', { id: tid }, title), button('', { variant: 'ghost', icon: 'x', onClick: close, ariaLabel: 'Close' })), body);
  const overlay = h('div', { class: 'overlay' }, box);
  closeFn = trap(overlay, box, close);
  return { body, close };
}

export function updatedStamp(onRefresh) {
  const stamp = h('span', { class: 'updated', 'aria-live': 'polite' });
  const set = () => { stamp.textContent = `Updated ${new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', hour: 'numeric', minute: '2-digit' }).format(new Date())}`; };
  set();
  return { el: h('span', { class: 'row' }, stamp, onRefresh ? button('Refresh', { variant: 'secondary', size: 'sm', icon: 'refresh', onClick: onRefresh }) : null), set };
}
