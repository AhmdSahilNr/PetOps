// Hash router. Deep links work (#/bookings/grooming/<id>); every visit re-fetches from the server (no client cache),
// so cross-role changes are never shown stale. A view token makes late responses from an earlier view harmless.
import { session } from './session.js';
import { match, POLICY } from './routes.js';

let token = 0;
let renderFn = null;

export function parse(hash = location.hash) {
  const raw = (hash || '').replace(/^#/, '') || '/';
  const [path, query = ''] = raw.split('?');
  return { path: path || '/', query: Object.fromEntries(new URLSearchParams(query)) };
}

export function href(path, query) {
  const q = query ? new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString() : '';
  return `#${path}${q ? `?${q}` : ''}`;
}

export function go(path, query) {
  const target = href(path, query);
  if (location.hash === target) render();
  else location.hash = target;
}

/** Replace the query on the current route without adding history (used to clear one-shot drill-down filters). */
export function replaceQuery(query) {
  const { path } = parse();
  history.replaceState(null, '', href(path, query));
}

export function start(fn) {
  renderFn = fn;
  window.addEventListener('hashchange', render);
  render();
}

export function render() {
  token += 1;
  const mine = token;
  const gen = session.generation;
  const { path, query } = parse();
  const role = session.user && session.user.role;
  const policy = POLICY[role];
  let route = role ? match(role, path) : null;
  if (role && !route) {
    // Unknown or other-role destination: land on this role's home. Server RBAC still guards all data.
    history.replaceState(null, '', href(policy.home));
    route = match(role, policy.home);
  }
  const ctx = {
    path: route ? (route.pattern.includes(':') ? path : route.pattern) : path,
    pattern: route && route.pattern, params: route ? route.params : {}, query, title: route && route.title,
    alive: () => mine === token && gen === session.generation,
  };
  return renderFn && renderFn(route, ctx);
}

export const currentToken = () => token;
