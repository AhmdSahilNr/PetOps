// Role shells: Customer portal (top bar), Staff/Admin workspace (sidebar). Built once per signed-in session.
import { h, icon } from './dom.js';
import { POLICY, navItems } from './routes.js';
import { href } from './router.js';
import { avatar, button } from './ui.js';
import { signOut } from './session.js';
import { get, qs } from './api.js';

const brand = (to) => h('a', { class: 'brand', href: href(to), 'aria-label': 'PetOps home' },
  h('span', { class: 'brand__mark' }, icon('paw')), h('span', { class: 'brand__name' }, 'PetOps'));

function roleLabel(role) { return { CUSTOMER: 'Customer', STAFF: 'Staff', ADMIN: 'Admin' }[role] || role; }

export function buildShell(user, onSignOut) {
  const policy = POLICY[user.role];
  const links = [];       // [{path, el}]
  const badges = {};      // name -> [el]
  const main = h('main', { id: 'main', tabIndex: -1, class: policy.shell === 'portal' ? 'portal__main' : 'ws__page' });
  const doSignOut = async () => { await signOut(); onSignOut(); };
  const badgeEl = (name) => { const b = h('span', { class: 'nav-badge', hidden: true }); (badges[name] ||= []).push(b); return b; };
  const navLink = (item, cls, withLabel = true) => {
    const a = h('a', { class: cls, href: href(item.path) }, icon(item.icon), withLabel ? h('span', { class: 'nav-item__label' }, item.label) : null,
      item.badge ? badgeEl(item.badge) : null);
    if (!withLabel) a.setAttribute('aria-label', item.label);
    links.push({ path: item.path, el: a });
    return a;
  };
  let root;
  if (policy.shell === 'portal') {
    const menu = h('div', { class: 'menu', hidden: true, id: 'account-menu' },
      h('div', { class: 'menu__head' }, h('b', {}, user.display_name || 'Your account'), h('span', {}, user.email)),
      h('a', { href: href('/account') }, icon('user'), 'Profile'),
      h('a', { href: href('/notifications') }, icon('bell'), 'Notifications'),
      h('button', { type: 'button', on: { click: doSignOut } }, icon('logout'), 'Sign out'));
    const menuBtn = h('button', { type: 'button', class: 'menu-button', 'aria-haspopup': 'true', 'aria-expanded': 'false', 'aria-controls': 'account-menu', 'aria-label': 'Account menu' },
      avatar(user.display_name || user.email), icon('chevron_down'));
    const toggle = (open) => { menu.hidden = !open; menuBtn.setAttribute('aria-expanded', String(open)); };
    menuBtn.addEventListener('click', (e) => { e.stopPropagation(); toggle(menu.hidden); });
    document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) toggle(false); });
    menu.addEventListener('keydown', (e) => { if (e.key === 'Escape') { toggle(false); menuBtn.focus(); } });
    menu.addEventListener('click', (e) => { if (e.target.closest('a')) toggle(false); });
    const bell = h('a', { class: 'icon-link', href: href('/notifications'), 'aria-label': 'Notifications' }, icon('bell'), badgeEl('notifications'));
    links.push({ path: '/notifications', el: bell });
    root = h('div', { class: 'portal' },
      h('header', { class: 'portal__top' }, h('div', { class: 'portal__bar' }, brand(policy.home),
        h('nav', { class: 'portal__links', 'aria-label': 'Main' }, policy.nav.map((n) => navLink(n, 'portal__link'))),
        h('div', { class: 'portal__actions' }, button('Book a service', { href: href('/book'), icon: 'plus' }), bell,
          h('div', { class: 'menu-wrap' }, menuBtn, menu)))),
      main,
      h('footer', { class: 'portal__foot' }, 'PetOps demonstration environment. All people, pets and bookings are fictional.'),
      h('nav', { class: 'tabbar', 'aria-label': 'Main' }, policy.mobile.map((n) => {
        const a = h('a', { href: href(n.path) }, icon(n.icon), n.label);
        links.push({ path: n.path, el: a });
        return a;
      })));
    root.querySelector('.portal__actions .btn').classList.add('btn--book');
  } else {
    const who = h('div', { class: 'ws__who' }, avatar(user.display_name || user.email, 'avatar--sm'),
      h('div', { class: 'ws__who-text' }, h('div', { class: 'ws__who-name' }, user.display_name || user.email), h('div', { class: 'ws__who-role' }, roleLabel(user.role))),
      h('a', { class: 'btn btn--ghost btn--sm btn--icon', href: href('/account'), 'aria-label': 'Profile', title: 'Profile' }, icon('user')),
      button('', { variant: 'ghost', size: 'sm', icon: 'logout', onClick: doSignOut, ariaLabel: 'Sign out' }));
    if (user.role === 'ADMIN') who.querySelector('a[aria-label="Profile"]').remove(); // Admin has no editable profile endpoint
    const side = h('nav', { class: 'ws__nav', 'aria-label': 'Main' }, brand(policy.home),
      policy.nav.map((g) => h('div', { class: 'nav-group', role: 'group', 'aria-label': g.group },
        h('div', { class: 'nav-group__title', 'aria-hidden': 'true' }, g.group), g.items.map((it) => navLink(it, 'nav-item')))), who);
    const mobileItems = user.role === 'ADMIN'
      ? [...navItems('ADMIN').filter((i) => policy.mobile.includes(i.path)), { path: '/more', label: 'More', icon: 'menu' }]
      : navItems(user.role);
    root = h('div', { class: 'ws' }, side,
      h('div', { class: 'ws__main' },
        h('div', { class: 'ws__mobilebar' }, brand(policy.home), h('div', { class: 'row' },
          user.role === 'STAFF' ? h('a', { class: 'btn btn--ghost btn--icon', href: href('/account'), 'aria-label': 'Profile' }, icon('user')) : null, // QA F-11
          button('', { variant: 'ghost', icon: 'logout', onClick: doSignOut, ariaLabel: 'Sign out' }))),
        h('div', { class: 'ws__content' }, main)),
      h('nav', { class: 'tabbar', 'aria-label': 'Main' }, mobileItems.map((n) => {
        const a = h('a', { href: href(n.path) }, icon(n.icon), n.label, n.badge ? badgeEl(n.badge) : null);
        links.push({ path: n.path, el: a });
        return a;
      })));
  }
  return {
    root, main,
    setActive(path) {
      root.dataset.path = path; // lets the shell hide its own "Book a service" button where the page already owns that action
      const top = '/' + (path.split('/').filter(Boolean)[0] || '');
      const settingsPath = path.startsWith('/settings/') ? path : null;
      for (const { path: p, el } of links) {
        const active = settingsPath ? p === settingsPath : (p === top || (p === '/more' && path === '/more'));
        if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
      }
    },
    setBadge(name, n) {
      for (const b of badges[name] || []) { b.hidden = !n; b.textContent = n > 99 ? '99+' : String(n || ''); b.setAttribute('aria-label', `${n} new`); }
    },
    async refreshBadges() {
      try {
        if (user.role === 'ADMIN') { const r = await get(`/admin/history${qs({ status: 'SUBMITTED', limit: 1 })}`); this.setBadge('decisions', r.total); }
        else { const r = await get(`/notifications${qs({ limit: 1 })}`); this.setBadge('notifications', r.unread_count); }
      } catch { /* badges are a convenience; pages show the authoritative data */ }
    },
  };
}
