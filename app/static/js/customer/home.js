// Customer Home: what is happening with my pets, what happens next, and one way to book.
// Layout: a wide two-part hero (next booking | book), then upcoming bookings beside pets and updates.
import { h, icon, replace } from '../core/dom.js';
import { href } from '../core/router.js';
import { chip, skeleton, errorState, avatar } from '../core/ui.js';
import { greeting, fmtLong, mytDate, relativeDay, bookingDate, scheduleText, fmtTime } from '../core/format.js';
import { customerNextStep, SERVICE } from '../core/labels.js';
import { loadCustomer, spotlight, upcoming, petSummary, detailPath } from './data.js';
import { dateBox, bookingRow } from './common.js';

export async function render(root, ctx) {
  const first = (ctx.user.display_name || '').split(' ')[0];
  const body = h('div', {}, skeleton(6));
  root.append(body);
  let data;
  try { data = await loadCustomer({ notifications: true }); } catch (e) { if (ctx.alive()) replace(body, errorState(e, ctx.refresh)); return; }
  if (!ctx.alive()) return;
  const pets = data.pets.filter((p) => p.is_active !== false);
  const focus = spotlight(data.bookings);
  const later = upcoming(data.bookings).filter((b) => !focus || b.id !== focus.id).slice(0, 4);
  const notes = ((data.notifications && data.notifications.items) || []).slice(0, 3);

  const next = focus ? customerNextStep(focus, focus.pet_name) : null;
  const hero = h('section', { class: 'home-hero', 'aria-labelledby': 'home-title' },
    h('div', { class: 'home-hero__main' },
      h('div', {}, h('h1', { id: 'home-title', tabIndex: -1 }, `${greeting()}${first ? `, ${first}` : ''}`), h('p', { class: 'home-hero__date' }, fmtLong(mytDate()))),
      focus ? h('a', { class: 'home-next', href: href(detailPath(focus)) },
        dateBox(bookingDate(focus)),
        h('div', { class: 'home-next__text' },
          h('div', { class: 'home-next__title' }, h('span', {}, focus.pet_name), chip(focus.status)),
          h('div', { class: 'home-next__meta' }, icon(SERVICE[focus.booking_type].icon), `${focus.service_name}, ${scheduleText(focus)}`),
          h('p', { class: 'home-next__step' }, next.title)),
        icon('chevron_right', { className: 'home-next__go' }))
        : h('p', { class: 'home-hero__empty' }, pets.length ? 'No bookings coming up.' : 'Add your pet, then book grooming or a stay.')),
    h('div', { class: 'home-hero__book' },
      h('h2', {}, 'Book a service'),
      h('div', { class: 'home-hero__kinds' }, h('span', {}, icon('scissors'), 'Grooming'), h('span', {}, icon('bed'), 'Boarding')),
      pets.length ? h('a', { class: 'btn btn--lg', href: href('/book') }, icon('plus'), 'Book a service')
        : h('a', { class: 'btn btn--lg', href: href('/pets', { add: 1 }) }, icon('plus'), 'Add a pet')));

  const upcomingSection = h('section', { class: 'home-section', 'aria-labelledby': 'h-upcoming' },
    h('div', { class: 'section-title' }, h('h2', { id: 'h-upcoming' }, 'Also coming up'), h('a', { href: href('/bookings') }, 'All bookings')),
    later.length ? h('div', { class: 'surface' }, h('div', { class: 'rows' }, later.map(bookingRow)))
      : h('p', { class: 'muted home-section__empty' }, 'Nothing else booked.'));

  const petsSection = h('section', { class: 'home-section', 'aria-labelledby': 'h-pets' },
    h('div', { class: 'section-title' }, h('h2', { id: 'h-pets' }, 'Your pets'), h('a', { href: href('/pets') }, 'Manage')),
    h('ul', { class: 'surface home-list' },
      pets.map((p) => {
        const s = petSummary(p, data.bookings);
        return h('li', {}, h('a', { href: href(`/pets/${p.id}`) }, avatar(p.name),
          h('span', {}, h('b', {}, p.name), h('span', { class: 'sub' }, s.next ? `${s.next.service_name}, ${relativeDay(bookingDate(s.next))}` : s.last ? `Last visit ${relativeDay(bookingDate(s.last))}` : 'No visits yet'))));
      }),
      h('li', {}, h('a', { href: href('/pets', { add: 1 }), class: 'home-list__add' }, h('span', { class: 'avatar' }, icon('plus')), h('span', {}, h('b', {}, 'Add a pet'))))));

  const updatesSection = notes.length ? h('section', { class: 'home-section', 'aria-labelledby': 'h-updates' },
    h('div', { class: 'section-title' }, h('h2', { id: 'h-updates' }, 'Latest updates'), h('a', { href: href('/notifications') }, 'View all')),
    h('ul', { class: 'surface home-list home-list--updates' }, notes.map((n) => h('li', { class: !n.read_at ? 'is-unread' : null },
      h('a', { href: href('/notifications') }, h('span', { class: 'home-list__dot', 'aria-hidden': 'true' }),
        h('span', {}, h('b', {}, n.pet_name ? n.title.replace(` \u2014 ${n.pet_name}`, '') : n.title),
          h('span', { class: 'sub' }, [n.pet_name, `${relativeDay(mytDate(n.created_at))}, ${fmtTime(n.created_at)}`].filter(Boolean).join(', ')))))))) : null;

  replace(body, hero, h('div', { class: 'home-cols' }, upcomingSection, h('div', { class: 'home-side' }, petsSection, updatesSection)));
}
