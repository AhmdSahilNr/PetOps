// Customer presentation pieces shared by Home, Bookings and Pets.
import { h, icon } from '../core/dom.js';
import { href } from '../core/router.js';
import { chip, serviceMark } from '../core/ui.js';
import { fmtWeekday, fmtDayNum, scheduleText, bookingDate } from '../core/format.js';
import { customerNextStep } from '../core/labels.js';
import { detailPath } from './data.js';

export function dateBox(dateStr) {
  const month = new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', month: 'short' }).format(new Date(`${dateStr}T00:00:00+08:00`));
  return h('div', { class: 'datebox', 'aria-hidden': 'true' }, h('div', { class: 'datebox__wk' }, fmtWeekday(dateStr)),
    h('div', { class: 'datebox__day' }, fmtDayNum(dateStr)), h('div', { class: 'datebox__mon' }, month));
}

/** The spotlight card: what is happening and what happens next. */
export function spotlightCard(b, { actions = [] } = {}) {
  const next = customerNextStep(b, b.pet_name);
  return h('article', { class: 'panel spot' }, dateBox(bookingDate(b)),
    h('div', { class: 'spot__main' },
      h('div', { class: 'spot__title' }, h('h3', {}, b.pet_name), chip(b.status)),
      h('div', { class: 'row row--wrap' }, serviceMark(b.booking_type, b.service_name)),
      h('div', { class: 'spot__when' }, scheduleText(b)),
      h('div', { class: 'next-step' }, h('b', {}, next.title), h('p', {}, next.text)),
      h('div', { class: 'row row--wrap', style: { 'margin-top': '8px' } }, h('a', { class: 'btn btn--secondary', href: href(detailPath(b)) }, 'View booking'), actions)));
}

/** A booking as a scannable row. */
export function bookingRow(b) {
  const d = bookingDate(b);
  const month = new Intl.DateTimeFormat('en-MY', { timeZone: 'Asia/Kuala_Lumpur', month: 'short' }).format(new Date(`${d}T00:00:00+08:00`));
  return h('a', { class: 'rowitem rowitem--link', href: href(detailPath(b)), style: { color: 'inherit', 'text-decoration': 'none' } },
    h('div', { class: 'rowitem__time', 'aria-hidden': 'true' }, h('b', {}, fmtDayNum(d)), h('span', {}, month)),
    h('div', { class: 'rowitem__main' },
      h('div', { class: 'rowitem__title' }, b.pet_name, h('span', { class: 'muted', style: { 'font-weight': '500' } }, b.service_name)),
      h('div', { class: 'rowitem__meta' }, h('span', {}, icon(b.booking_type === 'GROOMING' ? 'scissors' : 'bed'), b.booking_type === 'GROOMING' ? 'Grooming' : 'Boarding'), h('span', {}, scheduleText(b)))),
    h('div', { class: 'rowitem__side' }, chip(b.status), icon('chevron_right', { className: 'muted' })));
}
