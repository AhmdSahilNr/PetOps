// Admin "More" (phones): the destinations that do not fit the bottom bar, grouped like the sidebar.
import { h, icon } from '../core/dom.js';
import { href } from '../core/router.js';
import { pageHead } from '../core/ui.js';
import { POLICY } from '../core/routes.js';

export async function render(root) {
  const shown = new Set(POLICY.ADMIN.mobile);
  root.append(pageHead({ title: 'More' }), ...POLICY.ADMIN.nav.map((g) => h('section', { class: 'stack stack--sm', style: { 'margin-bottom': '20px' } },
    h('h2', { class: 'small muted' }, g.group),
    h('nav', { class: 'panel more-list', 'aria-label': g.group }, g.items.filter((i) => !shown.has(i.path)).map((i) => h('a', { href: href(i.path) }, icon(i.icon), i.label, icon('chevron_right', { className: 'chev' })))))));
}
