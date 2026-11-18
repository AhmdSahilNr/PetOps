// Role policy: the ONLY place that decides which destinations each role sees. It mirrors the server's
// RBAC (directive 03 \u00a713) but is never the control \u2014 every page's data comes from role-guarded endpoints.
export const POLICY = {
  CUSTOMER: {
    home: '/home', label: 'Customer', shell: 'portal',
    // One booking entry point: the "Book a service" button in the header (a tab on phones), never a nav item
    // beside "My bookings" (avoids "Book / Bookings").
    nav: [
      { path: '/home', label: 'Home', icon: 'home' },
      { path: '/bookings', label: 'My bookings', icon: 'list' },
      { path: '/pets', label: 'My pets', icon: 'paw' },
    ],
    mobile: [
      { path: '/home', label: 'Home', icon: 'home' },
      { path: '/bookings', label: 'Bookings', icon: 'list' },
      { path: '/book', label: 'Book', icon: 'plus' },
      { path: '/pets', label: 'Pets', icon: 'paw' },
      { path: '/account', label: 'Account', icon: 'user' },
    ],
    routes: [
      ['/home', 'Home', () => import('../customer/home.js')],
      ['/book', 'Book a service', () => import('../customer/book.js')],
      ['/bookings', 'My bookings', () => import('../customer/bookings.js')],
      ['/bookings/:type/:id', 'Booking', () => import('../customer/booking.js')],
      ['/pets', 'My pets', () => import('../customer/pets.js')],
      ['/pets/:id', 'Pet', () => import('../customer/pet.js')],
      ['/notifications', 'Notifications', () => import('../shared/notifications.js')],
      ['/account', 'Profile', () => import('../shared/account.js')],
    ],
  },
  STAFF: {
    home: '/work', label: 'Staff', shell: 'workspace',
    nav: [{ group: 'Work', items: [
      { path: '/work', label: 'My work', icon: 'list' },
      { path: '/agenda', label: 'Agenda', icon: 'agenda' },
      { path: '/history', label: 'History', icon: 'history' },
      { path: '/notifications', label: 'Notifications', icon: 'bell', badge: 'notifications' },
    ] }],
    routes: [
      ['/work', 'My work', () => import('../staff/work.js')],
      ['/work/:type/:id', 'Job', () => import('../staff/job.js')],
      ['/agenda', 'Agenda', () => import('../staff/agenda.js')],
      ['/history', 'My history', () => import('../staff/history.js')],
      ['/notifications', 'Notifications', () => import('../shared/notifications.js')],
      ['/account', 'Profile', () => import('../shared/account.js')],
    ],
  },
  ADMIN: {
    home: '/today', label: 'Admin', shell: 'workspace',
    nav: [
      { group: 'Operations', items: [
        { path: '/today', label: 'Today', icon: 'sun' },
        { path: '/bookings', label: 'Bookings', icon: 'list', badge: 'decisions' },
        { path: '/boarding', label: 'Boarding', icon: 'board' },
        { path: '/staff-work', label: 'Staff work', icon: 'users' },
        { path: '/history', label: 'History', icon: 'history' },
        { path: '/insights', label: 'Insights', icon: 'chart' },
      ] },
      { group: 'Settings', items: [
        { path: '/settings/services', label: 'Services', icon: 'tag' },
        { path: '/settings/staff', label: 'Staff accounts', icon: 'user' },
        { path: '/settings/accommodation', label: 'Boarding setup', icon: 'bed' },
        { path: '/settings/reminders', label: 'Reminders', icon: 'bell' },
        { path: '/settings/activity', label: 'Change log', icon: 'note' },
      ] },
    ],
    mobile: ['/today', '/bookings', '/boarding', '/insights'],
    routes: [
      ['/today', 'Today', () => import('../admin/today.js')],
      ['/bookings', 'Bookings', () => import('../admin/bookings.js')],
      ['/bookings/:type/:id', 'Booking', () => import('../admin/workspace.js')],
      ['/boarding', 'Boarding', () => import('../admin/boarding.js')],
      ['/staff-work', 'Staff work', () => import('../admin/staff-work.js')],
      ['/history', 'History', () => import('../admin/history.js')],
      ['/insights', 'Insights', () => import('../admin/insights.js')],
      ['/settings/services', 'Services', () => import('../admin/settings.js')],
      ['/settings/staff', 'Staff accounts', () => import('../admin/settings.js')],
      ['/settings/accommodation', 'Boarding setup', () => import('../admin/settings.js')],
      ['/settings/reminders', 'Reminders', () => import('../admin/settings.js')],
      ['/settings/activity', 'Change log', () => import('../admin/settings.js')],
      ['/more', 'More', () => import('../admin/more.js')],
    ],
  },
};

export function navItems(role) {
  const p = POLICY[role];
  if (!p) return [];
  return p.nav.flatMap((n) => (n.items ? n.items : [n]));
}

/** Match a path against a role's routes. Returns { title, load, params } or null. */
export function match(role, path) {
  const p = POLICY[role];
  if (!p) return null;
  for (const [pattern, title, load] of p.routes) {
    const a = pattern.split('/').filter(Boolean), b = path.split('/').filter(Boolean);
    if (a.length !== b.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < a.length; i += 1) {
      if (a[i].startsWith(':')) params[a[i].slice(1)] = decodeURIComponent(b[i]);
      else if (a[i] !== b[i]) { ok = false; break; }
    }
    if (ok) return { pattern, title, load, params };
  }
  return null;
}
