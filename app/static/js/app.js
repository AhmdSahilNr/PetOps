// PetOps entry point \u2014 the only module with load-time side effects.
import { clear, h } from './core/dom.js';
import { onUnauthorized } from './core/api.js';
import { probe, session, expire } from './core/session.js';
import { start, render as rerender, go } from './core/router.js';
import { buildShell } from './core/shell.js';
import { errorState, toast } from './core/ui.js';
import { renderAuth } from './shared/auth.js';

const app = document.getElementById('app');
let shell = null;
let shellGen = -1;

onUnauthorized(() => {
  if (!session.user) return;
  expire();
  toast('Your session has ended. Please sign in again.', 'error');
  rerender();
});

async function renderRoute(route, ctx) {
  // Drawers and dialogs belong to the page that opened them; never carry them across navigation.
  document.querySelectorAll('.overlay').forEach((o) => o.remove());
  document.body.style.removeProperty('overflow');
  if (!session.user) {
    shell = null; shellGen = -1;
    clear(app);
    document.title = 'Sign in \u00b7 PetOps';
    renderAuth(app, () => go('/'));
    return;
  }
  if (!shell || shellGen !== session.generation) {
    shell = buildShell(session.user, () => { shell = null; go('/'); });
    shellGen = session.generation;
    clear(app);
    app.appendChild(shell.root);
  }
  shell.setActive(ctx.path);
  document.title = `${ctx.title || 'PetOps'} \u00b7 PetOps`;
  const main = shell.main;
  clear(main);
  main.appendChild(h('div', { class: 'boot', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Loading'));
  try {
    const mod = await route.load();
    if (!ctx.alive()) return;
    clear(main);
    await mod.render(main, { ...ctx, user: session.user, refresh: rerender, shell });
    if (!ctx.alive()) return;
    const h1 = main.querySelector('h1');
    if (h1 && document.activeElement && !main.contains(document.activeElement)) h1.focus({ preventScroll: true });
  } catch (e) {
    if (!ctx.alive()) return;
    clear(main);
    main.appendChild(errorState(e, rerender));
  }
  shell && shell.refreshBadges();
}

// The skip link must move focus, not change the hash route (QA F-03).
document.addEventListener('click', (e) => {
  const link = e.target.closest && e.target.closest('.skip-link');
  if (!link) return;
  e.preventDefault();
  const main = document.getElementById('main');
  if (main) main.focus();
});

(async () => {
  await probe();
  start(renderRoute);
})();
