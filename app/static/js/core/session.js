// Current user and session generation. Every sign-in/out bumps `generation`, so late responses from an
// earlier session can never render into a newer one (keeps the intent of the old race guards).
import { api, post } from './api.js';

export const session = { user: null, generation: 0 };

export async function probe() {
  try { session.user = await api('/me'); } catch { session.user = null; }
  session.generation += 1;
  return session.user;
}

export async function signIn(email, password) {
  const res = await post('/auth/login', { email, password });
  session.user = res.user;
  session.generation += 1;
  return session.user;
}

export async function register(display_name, email, password) {
  await post('/auth/register', { display_name, email, password });
  return signIn(email, password);
}

export async function signOut() {
  try { await post('/auth/logout'); } catch { /* the server session may already be gone */ }
  expire();
}

export function expire() { session.user = null; session.generation += 1; }
export const role = () => session.user && session.user.role;
