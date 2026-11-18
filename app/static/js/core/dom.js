// Text-only DOM builder. Data is always inserted as text nodes; PetOps never parses HTML strings.
import { icon } from './icons.js';

const PROPS = new Set(['id', 'type', 'value', 'href', 'name', 'placeholder', 'required', 'disabled', 'checked', 'min', 'max',
  'step', 'autocomplete', 'title', 'rows', 'maxLength', 'minLength', 'tabIndex', 'hidden', 'readOnly', 'selected',
  'inputMode', 'pattern', 'htmlFor', 'colSpan', 'scope', 'open', 'multiple', 'size']);

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === 'class') el.className = Array.isArray(v) ? v.filter(Boolean).join(' ') : v;
      else if (k === 'text') el.textContent = String(v);
      else if (k === 'on') for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (k === 'style') for (const [sk, sv] of Object.entries(v)) el.style.setProperty(sk, String(sv));
      else if (k === 'dataset') for (const [dk, dv] of Object.entries(v)) el.dataset[dk] = dv;
      else if (k === 'for') el.htmlFor = v;
      else if (PROPS.has(k)) el[k] = v === true ? true : v;
      else el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of [children].flat(Infinity)) {
    if (c === null || c === undefined || c === false || c === '') continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function replace(el, ...children) { clear(el); return append(el, children); }
export { icon };

let uid = 0;
export const nextId = (prefix = 'id') => `${prefix}-${++uid}`;
